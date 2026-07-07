"""Deployment bootstrap: fetch the DuckDB on boot if it isn't already present locally, and
optionally verify its integrity.

Pure deployment glue — NO engine/comp/stats logic. The 187 MB DB is gitignored and not in the
repo, so a cloud host provisions it at boot from a URL. Local dev, where the DB already sits at
SCREENER_DB_PATH, is a strict no-op: nothing is downloaded, nothing is hashed, and behavior is
unchanged.

Contract (see ensure_db_present):
  * DB already present         -> no download; hash-checked only if SCREENER_DB_SHA256 is set.
  * DB missing + SCREENER_DB_URL set   -> stream-download, size-check, atomic move into place.
  * DB missing + SCREENER_DB_URL unset -> raise, naming both env vars (never boot broken).
  * Download too small (error page / truncation) -> raise, never open a corrupt DB.
  * SCREENER_DB_SHA256 set + hash mismatch -> raise (expected vs actual), delete the bad file so
    a redeploy re-downloads. Unset -> skip the check entirely (unchanged behavior).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import httpx

from . import config

DB_URL_ENV = "SCREENER_DB_URL"
DB_PATH_ENV = "SCREENER_DB_PATH"
DB_SHA256_ENV = "SCREENER_DB_SHA256"
MIN_DB_BYTES = 100 * 1024 * 1024   # 100 MB floor — the real DB is ~187 MB; guards against an
                                   # error page / truncated transfer landing as a "valid" file.
_CHUNK = 1 << 20                    # 1 MB streamed to disk at a time (never buffer 187 MB in RAM)


def _sha256_file(path: Path) -> str:
    """Streaming sha256 of a file (1 MB chunks — never loads 187 MB into memory)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_sha256(path: Path) -> None:
    """Optional integrity check. No-op unless SCREENER_DB_SHA256 is set. On mismatch, delete the
    bad file (so a redeploy re-downloads) and raise, naming expected vs actual."""
    expected = os.environ.get(DB_SHA256_ENV, "").strip().lower()
    if not expected:
        return                            # unset -> skip, unchanged behavior (strict no-op)
    actual = _sha256_file(path)
    if actual != expected:
        path.unlink(missing_ok=True)      # remove the bad file so the next boot re-downloads
        raise RuntimeError(
            f"Database at {path} failed {DB_SHA256_ENV} integrity check — refusing to boot. "
            f"expected {expected}, actual {actual}. Deleted the file; fix {DB_SHA256_ENV} (or the "
            f"release asset) and redeploy to re-download."
        )


def _download_db(path: Path) -> None:
    """Stream the DB from SCREENER_DB_URL to `path` (atomic), enforcing the size floor."""
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


def ensure_db_present(db_path: Path | None = None) -> Path:
    """Guarantee a valid DuckDB exists at `db_path` (defaults to config.DB_PATH) before it is
    opened: download it if missing, then verify its hash if SCREENER_DB_SHA256 is set.

    The hash check runs on BOTH paths (freshly downloaded or already present), so a
    large-but-corrupted file is caught, not only a truncated one. With the env var unset (local
    dev), no hashing happens and behavior is unchanged.
    """
    path = Path(db_path) if db_path is not None else config.DB_PATH
    if not path.exists():
        _download_db(path)                # raises on no URL / too-small download
    _verify_sha256(path)                  # no-op unless SCREENER_DB_SHA256 is set
    return path
