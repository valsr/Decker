"""Reading and safe extraction of .deckerplugin packages (untrusted zip archives)."""

import io
import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from decker.plugin.manifest import ManifestValidationError, PluginManifest

MAX_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_ENTRIES = 10_000
_MANIFEST_NAME = "manifest.json"
_S_IFMT = 0o170000
_S_IFLNK = 0o120000
_CHUNK = 64 * 1024


class PackageError(Exception):
    """A .deckerplugin package is unreadable, unsafe or has an invalid manifest."""


def _open_zip(data: bytes) -> zipfile.ZipFile:
    if len(data) > MAX_PACKAGE_BYTES:
        raise PackageError(f"package is too large (limit {MAX_PACKAGE_BYTES // (1024 * 1024)} MiB)")
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise PackageError("package is not a valid zip archive") from exc


def _check_name(name: str) -> None:
    if "\\" in name:
        raise PackageError(f"unsafe entry name (backslash): {name!r}")
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise PackageError(f"unsafe entry name (absolute path): {name!r}")
    if ".." in PurePosixPath(name).parts or ".." in name.split("/"):
        raise PackageError(f"unsafe entry name (parent traversal): {name!r}")
    if "\0" in name:
        raise PackageError(f"unsafe entry name (NUL byte): {name!r}")


def _validate_entries(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = zf.infolist()
    if len(infos) > MAX_ENTRIES:
        raise PackageError(f"package has too many entries (limit {MAX_ENTRIES})")
    seen: set[str] = set()
    file_names: set[str] = set()
    total = 0
    for info in infos:
        _check_name(info.filename)
        if (info.external_attr >> 16) & _S_IFMT == _S_IFLNK:
            raise PackageError(f"symlink entries are not allowed: {info.filename!r}")
        if info.flag_bits & 0x1:
            raise PackageError(f"encrypted entries are not allowed: {info.filename!r}")
        key = info.filename.rstrip("/")
        if key in seen:
            raise PackageError(f"duplicate entry: {info.filename!r}")
        seen.add(key)
        if not info.is_dir():
            file_names.add(info.filename)
        total += info.file_size
    if total > MAX_UNCOMPRESSED_BYTES:
        raise PackageError(
            f"package is too large when uncompressed (limit {MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MiB)"
        )
    if _MANIFEST_NAME not in file_names:
        raise PackageError(f"package has no {_MANIFEST_NAME} at its root")
    return infos


def _parse_manifest(raw: bytes) -> PluginManifest:
    try:
        parsed: Any = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PackageError(f"{_MANIFEST_NAME} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise PackageError(f"{_MANIFEST_NAME} must be a JSON object")
    try:
        return PluginManifest.from_dict(parsed)
    except ManifestValidationError as exc:
        raise PackageError(str(exc)) from exc


def _read_manifest_bytes(zf: zipfile.ZipFile) -> bytes:
    info = zf.getinfo(_MANIFEST_NAME)
    if info.is_dir():
        raise PackageError(f"{_MANIFEST_NAME} must be a file")
    if info.file_size > MAX_MANIFEST_BYTES:
        raise PackageError(f"{_MANIFEST_NAME} is too large (limit {MAX_MANIFEST_BYTES // 1024} KiB)")
    with zf.open(info) as src:
        raw = src.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise PackageError(f"{_MANIFEST_NAME} is too large (limit {MAX_MANIFEST_BYTES // 1024} KiB)")
    return raw


def read_manifest(data: bytes) -> PluginManifest:
    """Validate the archive and its manifest without writing anything."""
    try:
        with _open_zip(data) as zf:
            _validate_entries(zf)
            return _parse_manifest(_read_manifest_bytes(zf))
    except PackageError:
        raise
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise PackageError(f"package is corrupt: {exc!r}") from exc


def _extract_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, root: Path, written: int) -> int:
    target = (root / info.filename).resolve()
    if not target.is_relative_to(root):
        raise PackageError(f"entry escapes destination: {info.filename!r}")
    if info.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        return written
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.exists():
        raise PackageError(f"entry conflicts with an existing path: {info.filename!r}")
    with zf.open(info) as src, open(target, "xb") as out:
        while chunk := src.read(_CHUNK):
            written += len(chunk)
            if written > MAX_UNCOMPRESSED_BYTES:
                raise PackageError("package is too large when uncompressed")
            out.write(chunk)
    return written


def extract(data: bytes, dest: Path) -> PluginManifest:
    """Validate and extract a package into a new directory `dest` (must not exist); nothing remains on failure."""
    if dest.exists() or dest.is_symlink():
        raise PackageError(f"destination already exists: {dest}")
    created = False
    try:
        with _open_zip(data) as zf:
            infos = _validate_entries(zf)
            manifest = _parse_manifest(_read_manifest_bytes(zf))
            dest.mkdir(parents=True)
            created = True
            root = dest.resolve()
            written = 0
            for info in infos:
                written = _extract_member(zf, info, root, written)
            return manifest
    except BaseException as exc:
        if created:
            shutil.rmtree(dest, ignore_errors=True)
        if isinstance(exc, (PackageError, KeyboardInterrupt, SystemExit)):
            raise
        if not isinstance(exc, Exception):
            raise
        raise PackageError(f"package could not be extracted: {exc!r}") from exc
