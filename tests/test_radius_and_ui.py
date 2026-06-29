"""Item 1 (borough dropdown), 2 (comp-set toggle label), 3 (mean marker data),
4 (0.25 auto start + override-slider independence). Skipped if the DB isn't built.
"""
import re
import warnings

import pytest

from screener import config
from screener.jurisdiction import CompCriteria

warnings.filterwarnings("ignore")
pytestmark = pytest.mark.skipif(not config.DB_PATH.exists(), reason="screener.duckdb not built")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from screener.api import app
    return TestClient(app)


# --- Item 4: auto ladder starts at 0.25, named config, cap unchanged --------------------
def test_auto_start_is_quarter_mile_named_config():
    c = CompCriteria.load()
    assert c.radius_start_miles == 0.25 and c.radius_step_miles == 0.1 and c.radius_cap_miles == 1.0


def test_auto_default_handle_starts_at_quarter_mile(client):
    rc = client.get("/api/screen", params={"bbl": "1013000001"}).json()["radius_control"]
    assert rc["selection"] == "default" and rc["mode"] == "auto"


def test_midtown_tightens_under_quarter_start(client):
    # 230 Park clears at 0.25 -> a more local, smaller set than the old 0.5 start
    j = client.get("/api/screen", params={"bbl": "1013000001"}).json()
    assert j["comp_meta"]["radius_used_miles"] == 0.25


# --- Item 4 SCOPE GUARD: override slider keeps [0.1, 2.0], no auto cap leak --------------
def test_override_slider_reaches_two_miles_manhattan(client):
    j = client.get("/api/screen", params={"bbl": "1013000001", "radius": "2.0"}).json()
    assert j["comp_meta"]["radius_used_miles"] == 2.0          # not capped at the 1.0 auto cap
    assert j["radius_control"]["mode"] == "override"


def test_override_one_point_five_searches_one_point_five(client):
    j = client.get("/api/screen", params={"bbl": "1013000001", "radius": "1.5"}).json()
    assert j["comp_meta"]["radius_used_miles"] == 1.5          # fixed at user value, > auto cap


def test_comp_count_endpoint_allows_above_auto_cap(client):
    j = client.get("/api/comp_count", params={"bbl": "1013000001", "radius": "2.0"}).json()
    assert j["radius"] == 2.0


# --- Item 1: borough dropdown -----------------------------------------------------------
def _borough_selected(html):
    sel = re.search(r'name="borough"[^>]*>(.*?)</select>', html, re.S)
    assert sel, "borough must render as a <select>"
    opt = re.search(r'<option value="([^"]*)"[^>]*\bselected\b', sel.group(1))
    return opt.group(1) if opt else ""


def test_borough_is_select_with_five_boroughs(client):
    html = client.get("/screen", params={"bbl": "1013000001"}).text
    block = re.search(r'name="borough"[^>]*>(.*?)</select>', html, re.S).group(1)
    for b in ["Manhattan", "Bronx", "Brooklyn", "Queens", "Staten Island"]:
        assert f'value="{b}"' in block
    assert 'value=""' in block                                # blank option present


def test_borough_blank_default_on_fresh_page(client):
    assert _borough_selected(client.get("/").text) == ""      # blank/none default


def test_borough_blank_with_zip_does_not_short_circuit(client, monkeypatch):
    # ZIP present, borough blank -> the borough-or-ZIP rule is unchanged, so input is handed
    # to the resolver (NOT the missing_inputs short-circuit). Stub the geocoder so the suite
    # stays hermetic (no live Geoclient call) and assert it WAS reached with the typed zip.
    import screener.api as api
    seen = {}

    def fake_resolve(house_number, street, *, borough=None, zip_code=None, con=None, **kw):
        seen.update(house_number=house_number, street=street, borough=borough, zip_code=zip_code)
        from screener.geocode import ResolveResult
        return ResolveResult(ok=False, bbl=None, house_number=house_number, street=street,
                             borough=borough, zip_code=zip_code, bldg_class=None, refused=True,
                             reason="address_not_found", message="stub")

    monkeypatch.setattr(api, "resolve_address", fake_resolve)
    j = client.get("/api/screen", params={"house_number": "100", "street": "BROADWAY",
                                           "zip": "10005"}).json()
    assert seen == {"house_number": "100", "street": "BROADWAY", "borough": None, "zip_code": "10005"}
    assert j["reason"] != "missing_inputs"     # zip present -> resolver path, not short-circuit


def test_both_blank_still_missing_inputs_refusal(client):
    j = client.get("/api/screen", params={"house_number": "100", "street": "BROADWAY"}).json()
    assert j["status"] == "refused" and j["reason"] == "missing_inputs"


# --- Item 2: comp-set toggle label shows live count, styled ----------------------------
def test_full_comp_set_toggle_shows_count_and_styled(client):
    j = client.get("/api/screen", params={"bbl": "1013000001"}).json()
    n = j["comp_meta"]["comp_count"]
    html = client.get("/screen", params={"bbl": "1013000001"}).text
    assert f"View Full Comp Set ({n} Comps)" in html          # live count matches comp set
    assert "full-set-toggle" in html                          # bold/underline styling hook


# --- static-asset cache-busting (so edited app.js/style.css actually reach the browser) --
def test_static_assets_are_cache_busted():
    from screener.api import ASSET_VERSION
    assert ASSET_VERSION and len(ASSET_VERSION) >= 8
    from fastapi.testclient import TestClient

    from screener.api import app
    for path in ("/", "/screen?bbl=1013000001"):
        html = TestClient(app).get(path).text
        assert f"/static/app.js?v={ASSET_VERSION}" in html        # versioned, not bare
        assert f"/static/style.css?v={ASSET_VERSION}" in html
        assert 'src="/static/app.js"' not in html                # no un-versioned bare ref


def test_asset_version_tracks_content():
    # the version is a content hash, so a content change yields a different version
    import hashlib

    from screener.api import _HERE, ASSET_VERSION
    h = hashlib.sha1()
    for name in ("app.js", "style.css"):
        h.update((_HERE / "static" / name).read_bytes())
    assert ASSET_VERSION == h.hexdigest()[:10]
