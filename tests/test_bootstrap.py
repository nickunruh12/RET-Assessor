"""Deployment bootstrap (download-on-boot). Pure deploy glue — verifies the contract without
touching engine/comp/stats logic. The success/size-guard cases use a throwaway localhost HTTP
server (no external network), so they stay fast and deterministic.
"""
import http.server
import threading
from functools import partial

import pytest

from screener import bootstrap


def _serve(payload: bytes):
    """Start a localhost HTTP server that returns `payload` for any GET. Returns (url, stop)."""
    class _H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *a):  # silence
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}/db", srv.shutdown


def test_noop_when_db_present(tmp_path, monkeypatch):
    # DB already there (local dev) -> returns the path, no URL needed, no download.
    db = tmp_path / "screener.duckdb"
    db.write_bytes(b"already here")
    monkeypatch.delenv(bootstrap.DB_URL_ENV, raising=False)
    assert bootstrap.ensure_db_present(db) == db
    assert db.read_bytes() == b"already here"     # untouched


def test_missing_and_no_url_raises(tmp_path, monkeypatch):
    # Missing DB + no URL -> clear error naming BOTH env vars, never a silent/broken boot.
    monkeypatch.delenv(bootstrap.DB_URL_ENV, raising=False)
    with pytest.raises(RuntimeError) as e:
        bootstrap.ensure_db_present(tmp_path / "missing.duckdb")
    assert bootstrap.DB_URL_ENV in str(e.value) and bootstrap.DB_PATH_ENV in str(e.value)


def test_download_too_small_raises(tmp_path, monkeypatch):
    # A tiny body (e.g. an error page) is rejected by the size floor — no corrupt DB opened.
    url, stop = _serve(b"<html>404</html>")
    monkeypatch.setenv(bootstrap.DB_URL_ENV, url)
    db = tmp_path / "dl.duckdb"
    try:
        with pytest.raises(RuntimeError) as e:
            bootstrap.ensure_db_present(db)
        assert "bytes" in str(e.value)
        assert not db.exists()                    # nothing left at the final path
        assert not db.with_name(db.name + ".part").exists()   # sidecar cleaned up
    finally:
        stop()


def test_download_success_moves_into_place(tmp_path, monkeypatch):
    # A body over the (here-lowered) floor streams to disk and is atomically moved into place.
    payload = b"DUCKDBDATA" * 2000
    monkeypatch.setattr(bootstrap, "MIN_DB_BYTES", len(payload) - 1)
    url, stop = _serve(payload)
    monkeypatch.setenv(bootstrap.DB_URL_ENV, url)
    db = tmp_path / "sub" / "dl.duckdb"           # parent dir does not exist yet
    try:
        out = bootstrap.ensure_db_present(db)
        assert out == db and db.read_bytes() == payload
        assert not db.with_name(db.name + ".part").exists()
    finally:
        stop()
