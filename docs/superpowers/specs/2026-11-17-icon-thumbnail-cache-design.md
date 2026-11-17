# Icon thumbnail cache — design

Status: awaiting approval. Size: small change (client + one extra field from the server).

## Intent

The icon browser fetches every thumbnail from the server over RPC and rasterizes the SVG in the client each time it is
shown. Cache the rasterized thumbnails — in memory and on disk — so reopening the browser (or restarting Decker) shows
them at once without fetching or re-rendering. Display flow: memory hit, else disk hit, else fetch + render, then store in
both.

## Goals

- `IconThumbnailCache`: an in-memory LRU of `QPixmap`s in front of PNG files on disk.
- Key: `(pack id, plugin version, icon path, size px, tint colour)`. A thumbnail drawn for another theme colour or size is a
  different entry.
- Used by the icon browser thumbnails (64 px) and the `IconEdit` preview (24 px). Cached icons skip the `iconpack_icon` RPC
  entirely.
- **Invalidation on plugin update:** the plugin version is part of the key, and when a pack's version is seen to change the
  older version directories of that pack are deleted. Packs that are no longer installed are pruned the next time the
  browser loads the pack list.
- Works under `--prefix`: the cache lives in `<home>/cache/icons/` (`decker.common.paths`).

## Non-goals

- A size cap or expiry beyond version pruning (about 2–4 KB per icon; the 2001-icon solid pack is a few MB).
- Caching key images or anything on the server.
- Detecting a plugin re-installed with the **same** version but different icons (a plugin developer case; delete the cache
  directory).

## Design

- Server: `iconpacks_list` entries gain `plugin_version` (the manifest version). A client talking to an older server (no field)
  keeps the in-memory cache only.
- Client: `client/icon_cache.py` with `IconThumbnailCache.get(pack_id, version, path, size, tint) -> QPixmap | None` and
  `put(...)`, `prune(known: dict[str, str])`. Disk layout `<cache>/icons/<pack id>/<version>/<size>-<tint hex>/<sha256(path)[:32]>.png`
  (hashed file names, so icon paths can never escape the directory). Writes are atomic (temp file + rename); a failed write or
  an unreadable/corrupt PNG is treated as a miss and ignored (a corrupt file is removed).
- One process-wide instance, used by `IconBrowserDialog._pixmap_for/_load_next_icon` and `IconEdit._preview_pixmap`.
  Disk reads happen on the UI thread (small PNGs); misses keep using the existing one-RPC-per-turn queue.
- All decoded thumbnails are cached, not only SVGs: raster icons also avoid the RPC.

## Calls made without you

- Cache lives on the client; key includes tint; version-only invalidation as above.
