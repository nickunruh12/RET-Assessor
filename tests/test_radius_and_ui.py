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
    # the lookup form now lives on /screen (/ is the welcome page); default borough is blank
    assert _borough_selected(client.get("/screen").text) == ""      # blank/none default


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
    c = TestClient(app)
    # the tool page loads both versioned assets; the welcome page (/) has no charts, so it loads
    # only the versioned stylesheet (no app.js). Neither may carry an un-versioned bare ref.
    tool = c.get("/screen?bbl=1013000001").text
    assert f"/static/app.js?v={ASSET_VERSION}" in tool and f"/static/style.css?v={ASSET_VERSION}" in tool
    assert 'src="/static/app.js"' not in tool
    welcome = c.get("/").text
    assert f"/static/style.css?v={ASSET_VERSION}" in welcome
    assert 'href="/static/style.css"' not in welcome             # no un-versioned bare ref


def test_per_sf_label_is_dof_prefixed_everywhere(client):
    j = client.get("/api/screen", params={"bbl": "1013000001"}).json()
    sig = next(s for s in j["signals"] if s["key"] == "mv_per_gross_sf")
    assert sig["label"] == "DOF Market Value Per Gross Building Area"   # heading/title/tooltip
    assert "DOF Market Value Per Gross Building Area" in j["provenance"]["signal_fields"]
    assert "Market Value Per Gross Building Area" not in j["provenance"]["signal_fields"]  # no old key
    html = client.get("/screen", params={"bbl": "1013000001"}).text
    # every occurrence of the phrase on the page is the DOF-prefixed one (no bare leftover)
    assert html.count("Market Value Per Gross Building Area") == \
        html.count("DOF Market Value Per Gross Building Area") > 0


def test_chart_comp_points_carry_tooltip_metadata(client):
    j = client.get("/api/screen", params={"bbl": "1013000001"}).json()
    for sig in j["signals"]:
        if sig["refused"]:
            continue
        pts = sig["comp_points"]
        assert len(pts) == len(sig["distribution"])        # 1:1 with the plotted distribution
        for p in pts:
            assert set(p) >= {"x", "disp", "bbl", "address", "distance", "gap"}
            assert p["bbl"] and p["disp"]                  # never blank
        sp = sig["subject_point"]
        assert set(sp) >= {"x", "disp", "bbl", "address", "gap"}
        assert "distance" not in sp                        # subject has no distance-from-self


def test_chart_phase_in_gap_matches_comp_table(client):
    # tooltip phase-in gap == the 'Phase-In Gap Remaining' comp-table value (same single figure)
    j = client.get("/api/screen", params={"bbl": "1013000001"}).json()
    sig = next(s for s in j["signals"] if s["key"] == "assessed_value_market")
    by_bbl = {p["bbl"]: p["gap"] for p in sig["comp_points"]}
    rows = [r for v in j["variance"]["views"] for r in v["rows"]]
    for r in rows:
        if r["parcel_id"] in by_bbl:
            assert by_bbl[r["parcel_id"]] == r["phase_in_gap_display"]


def test_asset_version_tracks_content():
    # the version is a content hash, so a content change yields a different version
    import hashlib

    from screener.api import _HERE, ASSET_VERSION
    h = hashlib.sha1()
    for name in ("app.js", "style.css"):
        h.update((_HERE / "static" / name).read_bytes())
    assert ASSET_VERSION == h.hexdigest()[:10]


# --- Radius override drives K/F comp selection (slider now live for retail + industrial) -----
# The manual radius BOUNDS the search; the per-class quality cascade still runs within it and the
# 8-comp refusal gate is preserved. Office is unchanged. comp_count and the rendered screen share
# one radius_override mechanism, so they must agree at the chosen radius.
_K_BBL = "1000200012"   # K4 pure retail (lower Manhattan)
_F_BBL = "3000320029"   # F5 industrial (Brooklyn)
_O_BBL = "1013010001"   # office


@pytest.mark.parametrize("bbl", [_K_BBL, _F_BBL])
def test_kf_screen_responds_to_manual_radius(client, bbl):
    # a numeric radius flips the control to OVERRIDE and bounds the screen at that radius,
    # instead of the old behavior where K/F ignored the slider and used the auto-radius.
    j = client.get("/api/screen", params={"bbl": bbl, "radius": "1.0"}).json()
    assert j["status"] == "ok"
    rc = j["radius_control"]
    assert rc["mode"] == "override" and rc["selection"] == "1"
    assert j["comp_meta"]["radius_used_miles"] <= 1.0 + 1e-9


@pytest.mark.parametrize("bbl,radius", [(_K_BBL, "1.0"), (_F_BBL, "2")])
def test_kf_comp_count_matches_screen_at_manual_radius(client, bbl, radius):
    # the live slider count equals the comp set the screen actually renders at that radius.
    screen = client.get("/api/screen", params={"bbl": bbl, "radius": radius}).json()
    assert screen["status"] == "ok"
    cc = client.get("/api/comp_count", params={"bbl": bbl, "radius": radius}).json()
    assert cc["count"] == screen["comp_meta"]["comp_count"]


@pytest.mark.parametrize("bbl", [_K_BBL, _F_BBL])
def test_kf_refuses_when_bounded_search_cannot_reach_min(client, bbl):
    # a very tight radius that can't field 8 comps refuses — the override never bypasses the gate.
    j = client.get("/api/screen", params={"bbl": bbl, "radius": "0.1"}).json()
    assert j["status"] == "refused" and j["reason"] == "insufficient_comps_within_cap"


def test_office_radius_dispatch_unchanged(client):
    # office still routes comp_count to the office selector and stays in AUTO by default; the
    # live count matches the office screen's comp set at its auto radius (office byte-identical).
    screen = client.get("/api/screen", params={"bbl": _O_BBL}).json()
    assert screen["status"] == "ok" and screen["radius_control"]["mode"] == "auto"
    cc = client.get("/api/comp_count",
                    params={"bbl": _O_BBL, "radius": screen["comp_meta"]["radius_used_miles"]}).json()
    assert cc["count"] == screen["comp_meta"]["comp_count"]


# --- Radius slider is a read-only reflection of the resolved radius (display only) -----------
def _slider(html):
    return re.search(r'<input type="range"[^>]*>', html).group(0)


@pytest.mark.parametrize("bbl", [_O_BBL, _K_BBL, _F_BBL])
def test_slider_thumb_binds_to_resolved_radius(client, bbl):
    # PART 1: the slider's initial value == the screen's resolved radius_used, so the thumb
    # position matches the "Radius used" label on initial render (in-range parcels).
    j = client.get("/api/screen", params={"bbl": bbl}).json()
    ru = j["comp_meta"]["radius_used_miles"]
    html = client.get("/screen", params={"bbl": bbl}).text
    inp = _slider(html)
    value = float(re.search(r'value="([^"]+)"', inp).group(1))
    assert value == pytest.approx(ru)          # thumb bound to the same source as the label
    assert "disabled" not in inp               # in-range parcels keep an active slider


def test_beyond_range_parcel_shows_explicit_state_not_pegged_max(client):
    # PART 2: a citywide big-box parcel resolves > 2.0 mi; the slider can't represent it, so it
    # is disabled and the label states the real radius + "beyond ... override range" — the thumb
    # is never silently read as a literal 2.0.
    BIGBOX_F = "5041910038"   # F5, shortfall-extends to ~2.8mi (> 2.0 slider max)
    j = client.get("/api/screen", params={"bbl": BIGBOX_F}).json()
    ru = j["comp_meta"]["radius_used_miles"]
    assert ru > 2.0                            # precondition: genuinely beyond the slider max
    html = client.get("/screen", params={"bbl": BIGBOX_F}).text
    assert "beyond-range" in html and "disabled" in _slider(html)
    assert "beyond the 2 mi override range" in html
    assert f"Radius used: {ru:g} mi" in html   # the real radius is stated, not the max
