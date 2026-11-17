"""Plugin repository store: fetching, caching and merging repository indexes."""

import hashlib
import json
import logging
import os
import shutil
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from decker.common import config
from decker.plugin.repository_index import (
    MAX_INDEX_BYTES,
    IndexPlugin,
    RepositoryIndex,
    RepositoryIndexError,
    parse_index,
)

logger = logging.getLogger(__name__)

MAX_ICON_BYTES = 512 * 1024
_ALLOWED_SCHEMES = ("http://", "https://", "file://")
_CONFIG_KEY = "plugin.repositories"
_CHUNK = 64 * 1024


class FetchError(Exception):
    """Raised when a URL cannot be fetched."""


class RepositoryError(Exception):
    """Raised when a repository cannot be added or used."""


@dataclass(frozen=True)
class RepositoryInfo:
    """Summary of a configured repository."""

    url: str
    name: str
    plugin_count: int
    last_checked: float | None
    error: str | None


@dataclass(frozen=True)
class CatalogEntry:
    """A plugin offered by a repository, with the repository that shadows it (if any)."""

    plugin: IndexPlugin
    repository_url: str
    shadowed_by: str | None


def fetch(url: str, max_bytes: int, timeout: float = 20.0) -> bytes:
    """Fetch an http, https or file URL, refusing bodies larger than max_bytes."""
    if not url.lower().startswith(_ALLOWED_SCHEMES):
        raise FetchError(f"Unsupported URL scheme: {url}")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # nosec B310 - scheme checked above
            data: bytes = response.read(max_bytes + 1)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise FetchError(f"Cannot fetch {url}: {exc}") from exc
    if len(data) > max_bytes:
        raise FetchError(f"Response from {url} exceeds {max_bytes} bytes")
    return data


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    _write_atomic(path, json.dumps(data).encode("utf-8"))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class RepositoryStore:
    """Configured plugin repositories with an on-disk cache of their indexes."""

    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir: Path = cache_dir
        self._lock: threading.RLock = threading.RLock()

    def urls(self) -> list[str]:
        """Return the configured repository URLs in priority order."""
        value = config.get_or_default(_CONFIG_KEY, [])
        return [str(item) for item in value] if isinstance(value, list) else []

    def list_repositories(self) -> list[RepositoryInfo]:
        """Return a summary of every configured repository."""
        with self._lock:
            return [self._info(url) for url in self.urls()]

    def add(self, url: str) -> RepositoryInfo:
        """Fetch, validate and save a new repository."""
        with self._lock:
            if url in self.urls():
                raise RepositoryError(f"Repository already added: {url}")
            try:
                raw = fetch(url, MAX_INDEX_BYTES)
                parse_index(raw, url)
            except (FetchError, RepositoryIndexError) as exc:
                raise RepositoryError(str(exc)) from exc
            self._store_index(url, raw)
            config.set(_CONFIG_KEY, [*self.urls(), url])
            return self._info(url)

    def remove(self, url: str) -> bool:
        """Remove a repository and its cache; return False if it was not configured."""
        with self._lock:
            urls = self.urls()
            if url not in urls:
                return False
            config.set(_CONFIG_KEY, [item for item in urls if item != url])
            shutil.rmtree(self._dir(url), ignore_errors=True)
            return True

    def refresh_all(self) -> list[RepositoryInfo]:
        """Refetch every repository; a failure keeps the cached index and records the error."""
        with self._lock:
            for url in self.urls():
                self._refresh(url)
            return self.list_repositories()

    def catalog(self) -> list[CatalogEntry]:
        """Return all cached plugins; the first repository offering an id wins."""
        with self._lock:
            owners: dict[str, str] = {}
            entries: list[CatalogEntry] = []
            for url in self.urls():
                index = self._load_index(url)
                if index is None:
                    continue
                for plugin in index.plugins:
                    owner = owners.setdefault(plugin.id, url)
                    entries.append(CatalogEntry(plugin, url, None if owner == url else owner))
            return entries

    def find(self, plugin_id: str) -> CatalogEntry | None:
        """Return the non-shadowed catalog entry for a plugin id."""
        for entry in self.catalog():
            if entry.plugin.id == plugin_id and entry.shadowed_by is None:
                return entry
        return None

    def icon(self, plugin_id: str) -> bytes | None:
        """Return the plugin's icon, fetching and caching it on first use."""
        entry = self.find(plugin_id)
        if entry is None or not entry.plugin.icon_url:
            return None
        with self._lock:
            path = self._dir(entry.repository_url) / "icons" / plugin_id
            if path.is_file():
                return path.read_bytes()
            try:
                data = fetch(entry.plugin.icon_url, MAX_ICON_BYTES)
            except FetchError as exc:
                logger.warning("Icon fetch failed for %s: %s", plugin_id, exc)
                return None
            _write_atomic(path, data)
            return data

    def last_check(self) -> float | None:
        """Return the time of the last update check, if any."""
        value = _read_json(self._cache_dir / "state.json").get("last_check")
        return float(value) if isinstance(value, (int, float)) else None

    def mark_checked(self, when: float) -> None:
        """Record the time of the last update check."""
        with self._lock:
            _write_json(self._cache_dir / "state.json", {"last_check": when})

    def _dir(self, url: str) -> Path:
        return self._cache_dir / hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]  # nosec B324

    def _store_index(self, url: str, raw: bytes) -> None:
        directory = self._dir(url)
        _write_atomic(directory / "index.json", raw)
        shutil.rmtree(directory / "icons", ignore_errors=True)
        self._write_meta(url, None)

    def _write_meta(self, url: str, error: str | None) -> None:
        _write_json(self._dir(url) / "meta.json", {"url": url, "last_checked": _now(), "error": error})

    def _refresh(self, url: str) -> None:
        try:
            raw = fetch(url, MAX_INDEX_BYTES)
            parse_index(raw, url)
        except (FetchError, RepositoryIndexError) as exc:
            logger.warning("Refreshing repository %s failed: %s", url, exc)
            self._write_meta(url, str(exc))
            return
        self._store_index(url, raw)

    def _load_index(self, url: str) -> RepositoryIndex | None:
        try:
            return parse_index((self._dir(url) / "index.json").read_bytes(), url)
        except (OSError, RepositoryIndexError):
            return None

    def _info(self, url: str) -> RepositoryInfo:
        meta = _read_json(self._dir(url) / "meta.json")
        index = self._load_index(url)
        checked = meta.get("last_checked")
        error = meta.get("error")
        return RepositoryInfo(
            url=url,
            name=index.name if index else url,
            plugin_count=len(index.plugins) if index else 0,
            last_checked=float(checked) if isinstance(checked, (int, float)) else None,
            error=str(error) if error else None,
        )


def _now() -> float:
    return time.time()
