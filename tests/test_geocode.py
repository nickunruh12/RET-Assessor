"""Resolver tests. The geocode HTTP call is mocked (deterministic, no network); the
BBL validation runs against the real loaded DB. Live API calls live in
scripts/validate_geocode.py.
"""
import duckdb
import httpx
import pytest

from screener import config, geocode
from screener.geocode import (
    GeoclientConfigError,
    _geocode_bbl,
    _validate_bbl,
    get_api_key,
    resolve_address,
)


class _FakeResp:
    def __init__(self, status, payload, bad_json=False):
        self.status_code = status
        self._payload = payload
        self._bad = bad_json

    def json(self):
        if self._bad:
            raise ValueError("bad json")
        return self._payload


# --- key handling ----------------------------------------------------------
def test_missing_key_raises_clear_error(monkeypatch):
    monkeypatch.setattr(geocode, "_load_dotenv", lambda p: None)   # don't read real .env
    monkeypatch.delenv(geocode.ENV_VAR, raising=False)
    with pytest.raises(GeoclientConfigError) as e:
        get_api_key()
    assert geocode.ENV_VAR in str(e.value)


def test_key_read_from_env(monkeypatch):
    monkeypatch.setattr(geocode, "_load_dotenv", lambda p: None)
    monkeypatch.setenv(geocode.ENV_VAR, "test-key-123")
    assert get_api_key() == "test-key-123"


# --- geocode extraction (mocked HTTP) --------------------------------------
def test_extracts_bbl_nested(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResp(200, {"address": {"bbl": "1002230035", "x": 1}}))
    assert _geocode_bbl("438", "Greenwich St", "Manhattan", None, "k") == ("1002230035", None)


def test_extracts_bbl_flat(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResp(200, {"bbl": "1006400041"}))
    assert _geocode_bbl("356", "West 12 St", "Manhattan", None, "k") == ("1006400041", None)


def test_no_bbl_is_address_not_found(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResp(200, {"address": {"message": "not found"}}))
    assert _geocode_bbl("99999", "Nowhere Blvd", "Manhattan", None, "k") == (None, "address_not_found")


def test_unauthorized_is_flagged(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResp(401, {}))
    assert _geocode_bbl("438", "Greenwich St", "Manhattan", None, "k") == (None, "geoclient_unauthorized")


def test_http_error_is_address_not_found(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx, "get", boom)
    assert _geocode_bbl("438", "Greenwich St", "Manhattan", None, "k") == (None, "address_not_found")


def test_missing_inputs_refused_without_network():
    r = resolve_address("438", "Greenwich St", con=None)   # no borough or zip
    assert r.refused and r.reason == "missing_inputs"


# --- BBL validation against the real loaded engine data --------------------
needs_db = pytest.mark.skipif(not config.DB_PATH.exists(), reason="screener.duckdb not built")


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(str(config.DB_PATH), read_only=True)
    yield c
    c.close()


@needs_db
def test_validate_office_bbl_ok(con):
    r = _validate_bbl(con, "1002230035")           # 438 Greenwich, O1
    assert r.ok and not r.refused and r.bldg_class.startswith("O")


@needs_db
def test_validate_non_office_class4_out_of_scope(con):
    r = _validate_bbl(con, "3000250001")           # K4 store, class 4
    assert r.refused and r.reason == "out_of_scope_v1"


@needs_db
def test_validate_tax_exempt(con):
    r = _validate_bbl(con, "1000380001")           # O4 exempt, curmkttot 0
    assert r.refused and r.reason == "subject_tax_exempt"


@needs_db
def test_validate_not_in_class4_roll(con):
    r = _validate_bbl(con, "9999999999")
    assert r.refused and r.reason == "not_class_4"


@needs_db
def test_full_resolve_with_mocked_geocode(con, monkeypatch):
    # End-to-end with the network step stubbed: a valid office BBL flows through.
    monkeypatch.setattr(geocode, "_geocode_bbl",
                        lambda *a, **k: ("1002230035", None))
    r = resolve_address("438", "Greenwich Street", borough="Manhattan", con=con, key="k")
    assert r.ok and r.bbl == "1002230035"
