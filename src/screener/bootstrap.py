"""Deployment bootstrap: fetch the DuckDB on boot if it isn't already present locally.

Pure deployment glue — NO engine/comp/stats logic. The 187 MB DB is gitignored and not in the
repo, so a cloud host provisions it at boot from a URL. Local dev, where the DB already sits at
SCREENER_DB_PATH, is a strict no-op: nothing is downloaded and behavior is unchanged.

Contract (see ensure_db_present):
  * DB already present         -> no-op.
  * DB missing + SCREENER_DB_URL set   -> stream-download, size-check, atomic move into place.
  * DB missing + SCREENER_DB_URL unset -> raise, naming both env vars (never boot broken).
  * Download too small (error page / truncation) -> raise, never open a corrupt DB.
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx

from . import config

DB_URL_ENV = "SCREENER_DB_URL"
DB_PATH_ENV = "SCREENER_DB_PATH"
MIN_DB_BYTES = 100 * 1024 * 1024   # 100 MB floor — the real DB is ~187 MB; guards against an
                                   # error page / truncated transfer landing as a "valid" file.
_CHUNK = 1 << 20                    # 1 MB streamed to disk at a time (never buffer 187 MB in RAM)


def ensure_db_present(db_path: Path | None = None) -> Path:
    """Guarantee the DuckDB exists at `db_path` (defaults to config.DB_PATH) before it is opened.

    Downloads from SCREENER_DB_URL only when the file is missing; otherwise does nothing.
    """
    path = Path(db_path) if db_path is not None else config.DB_PATH
    if path.exists():
        return path                       # local dev / already provisioned — do nothing

    url = os.environ.get(DB_URL_ENV, "").strip()
    if not url:
        raise RuntimeError(
            f"Database not found at {path} and {DB_URL_ENV} is unset. On a host, set "
            f"{DB_PATH_ENV} to the DB location and {DB_URL_ENV} to a URL to download it from "
            f"(or provision the file at that path before boot)."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")   # download to a sidecar, move in only when valid
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(60.0, read=None)) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=_CHUNK):
                    fh.write(chunk)
    except httpx.HTTPError as e:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to download the database from {DB_URL_ENV} ({url!r}): {e}") from e

    size = tmp.stat().st_size
    if size < MIN_DB_BYTES:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"Downloaded database from {DB_URL_ENV} is only {size:,} bytes "
            f"(< {MIN_DB_BYTES:,} floor); the URL likely returned an error page, not the DB. "
            f"Refusing to open a corrupt file."
        )
    os.replace(tmp, path)                 # atomic: the final path only ever holds a validated file
    return path
