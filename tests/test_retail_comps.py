"""Retail Stage-2 comp pools. Real class-4 K parcels screened via the engine / test route.
Skipped if the DB (with retail_class) is not built. Office is asserted unchanged elsewhere.
"""
import warnings

import duckdb
import pytest

from screener import config
from screener.jurisdiction import CompCriteria, get_jurisdiction
from screener.retail_comps import select_retail_comps

warnings.filterwarnings("ignore")
pytestmark = pytest.mark.skipif(not config.DB_PATH.exists(), reason="screener.duckdb not built")

PURE = "1000200012"        # 47 Broadway, K4 >=80% retail -> pure_retail
OFFICE = "1000630018"      # 179 Broadway, K2 retail+office
RESID = "1000100032"       # 6 Stone St, K4 retail+residential
BAND_RELAX = "2023330010"  # retail_other, clears via band-relax (stage 2)
FALLBACK = "2054230001"    # retail_other, clears via broader-retail fallback (stage 3)


@pytest.fixture(scope="module")
def env():
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    has = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='retail_class'").fetchone()[0]
    if not has:
        pytest.skip("retail_class table not loaded")
    yield con, CompCriteria.load(), get_jurisdiction("nyc")
    con.close()


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from screener.api import app
    return TestClient(app)


# --- per-class screening via the test route ------------------------------------------
def test_pure_retail_three_charts_per_sf_shown(client):
    j = client.get("/api/retail_screen", params={"bbl": PURE}).json()
    assert j["status"] == "ok"
    by = {s["key"]: s for s in j["signals"]}
    assert by["mv_per_gross_sf"]["refused"] is False            # per-SF shown
    assert by["assessed_value_market"]["refused"] is False and by["tax_bill"]["refused"] is False
    assert j["comp_meta"]["radius_used_miles"] <= 1.0           # pure cap


def test_mixed_office_per_sf_refused_value_tax_render(client):
    j = client.get("/api/retail_screen", params={"bbl": OFFICE}).json()
    by = {s["key"]: s for s in j["signals"]}
    assert by["mv_per_gross_sf"]["refused"] is True
    assert "blends retail with other uses" in by["mv_per_gross_sf"]["message"]
    assert by["assessed_value_market"]["refused"] is False and by["tax_bill"]["refused"] is False
    assert j["classification_note"] and "K2" in j["classification_note"]
    assert j["comp_meta"]["radius_used_miles"] <= 1.5


def test_mixed_residential_pattern(client):
    j = client.get("/api/retail_screen", params={"bbl": RESID}).json()
    by = {s["key"]: s for s in j["signals"]}
    assert by["mv_per_gross_sf"]["refused"] is True
    assert "retail + residential" in j["classification_note"]


# --- SF band actually filters --------------------------------------------------------
def test_sf_band_filters_comps(env):
    con, crit, juris = env
    cs, meta = select_retail_comps(con, OFFICE, juris, crit)
    assert cs.sf_band_applied
    sf = cs.subject["sf"]
    assert all(0.5 * sf <= c.sf <= 1.5 * sf for c in cs.comps)   # all within +/-50%


# --- relax cascade, in order, never past cap -----------------------------------------
def test_band_relax_stage(env):
    con, crit, juris = env
    cs, meta = select_retail_comps(con, BAND_RELAX, juris, crit)
    assert not cs.refused and cs.count >= crit.min_comp_count
    assert cs.sf_band_applied is False and cs.fallback_triggered is False   # band relaxed, same mix
    assert cs.adjacent_count == 0                                           # still same category
    assert cs.radius_used_miles <= crit.retail_radius_caps[meta.category] + 1e-9


def test_broader_fallback_prefers_same_mix_and_caps(env):
    con, crit, juris = env
    cs, meta = select_retail_comps(con, FALLBACK, juris, crit)
    assert cs.fallback_triggered and cs.adjacent_count >= 1                 # cross-use pulled
    assert cs.exact_count >= 1                                              # same-mix preferred (included first)
    assert cs.radius_used_miles <= crit.retail_radius_caps[meta.category] + 1e-9   # never past cap
    assert meta.fallback_note and "other retail use-types" in meta.fallback_note


def test_refusal_never_widens_past_cap(env):
    con, crit, juris = env
    tight = crit.model_copy(update={"retail_radius_caps": {**crit.retail_radius_caps,
                                                           "pure_retail": 0.02}})
    cs, meta = select_retail_comps(con, PURE, juris, tight)
    assert cs.refused and cs.note == "insufficient_comps_within_cap"
    assert (cs.radius_used_miles or 0) <= 0.02 + 1e-9          # did not silently widen


# --- public screen still refuses K; office unchanged ---------------------------------
def test_band_relaxed_message_not_sf_missing(client):
    # retail fallback relaxed the band; subject HAS SF -> band-relaxed message, NOT "SF not reported"
    j = client.get("/api/retail_screen", params={"bbl": FALLBACK}).json()
    assert j["subject"]["gross_sf"] and j["comp_meta"]["sf_band_relaxed"] is True
    assert j["comp_meta"]["sf_band_applied"] is False
    html = client.get("/retail_screen", params={"bbl": FALLBACK}).text
    assert "gross-SF band relaxed to reach the 8-comp minimum" in html
    assert "subject SF not reported" not in html


def test_office_sf_missing_message_unchanged(client):
    # genuine subject-SF-null case keeps the original message, sf_band_relaxed stays False
    j = client.get("/api/screen", params={"bbl": "3053480042"}).json()
    assert j["comp_meta"]["sf_band_relaxed"] is False and j["comp_meta"]["sf_band_applied"] is False
    html = client.get("/screen", params={"bbl": "3053480042"}).text
    assert "no gross-SF band: subject SF not reported" in html
    assert "band relaxed to reach" not in html


def test_band_held_shows_no_message(client):
    # retail_office (179 Broadway) clears WITH the band applied -> neither message renders
    j = client.get("/api/retail_screen", params={"bbl": OFFICE}).json()
    assert j["comp_meta"]["sf_band_applied"] is True and j["comp_meta"]["sf_band_relaxed"] is False
    html = client.get("/retail_screen", params={"bbl": OFFICE}).text
    assert "subject SF not reported" not in html and "band relaxed to reach" not in html


PURE_BAND_RELAX = "1000200012"   # pure_retail, per-SF SHOWN, band relaxed -> size-outlier flags
PURE_BAND_HELD = "1000070027"    # pure_retail, per-SF shown, band held -> clean, no flags


def test_per_sf_size_flag_on_pure_band_relax(client):
    j = client.get("/api/retail_screen", params={"bbl": PURE_BAND_RELAX}).json()
    assert j["comp_meta"]["sf_band_relaxed"] is True
    assert j.get("per_sf_size_flag") is True
    sig = next(s for s in j["signals"] if s["key"] == "mv_per_gross_sf")
    assert sig["refused"] is False                                   # per-SF KEPT, not suppressed
    assert "size_flag_note" in sig                                   # chart header note
    flagged = [p for p in sig["comp_points"] if p.get("size_dissimilar")]
    assert flagged, "expected size-dissimilar comps marked on the per-SF chart"
    html = client.get("/retail_screen", params={"bbl": PURE_BAND_RELAX}).text
    assert 'class="size-flag"' in html                               # per-row table tag
    assert "Size-dissimilar comps marked below" in html                   # header note
    assert "outlier" not in html.lower()                             # banned word stays out


def test_value_tax_charts_not_size_flagged(client):
    j = client.get("/api/retail_screen", params={"bbl": PURE_BAND_RELAX}).json()
    for key in ("assessed_value_market", "tax_bill"):
        sig = next(s for s in j["signals"] if s["key"] == key)
        assert not any(p.get("size_dissimilar") for p in sig["comp_points"])
        assert "size_flag_note" not in sig


def test_band_held_set_has_no_size_flags(client):
    j = client.get("/api/retail_screen", params={"bbl": PURE_BAND_HELD}).json()
    assert j["comp_meta"]["sf_band_relaxed"] is False and j.get("per_sf_size_flag") in (None, False)
    sig = next(s for s in j["signals"] if s["key"] == "mv_per_gross_sf")
    assert sig["refused"] is False and "size_flag_note" not in sig
    html = client.get("/retail_screen", params={"bbl": PURE_BAND_HELD}).text
    assert 'class="size-flag"' not in html and "Size-dissimilar comps marked below" not in html


def test_mixed_suppressed_per_sf_has_no_size_flags(client):
    # mixed retail still suppresses per-SF (use-blend); size flagging does NOT apply there
    j = client.get("/api/retail_screen", params={"bbl": FALLBACK}).json()
    sig = next(s for s in j["signals"] if s["key"] == "mv_per_gross_sf")
    assert sig["refused"] is True                                    # suppression unchanged
    assert j.get("per_sf_size_flag") in (None, False)
    assert not any(p.get("size_dissimilar") for p in sig.get("comp_points", []))
    html = client.get("/retail_screen", params={"bbl": FALLBACK}).text
    assert "Size-dissimilar comps marked below" not in html


def test_office_has_no_size_flag(client):
    j = client.get("/api/screen", params={"bbl": "1013000001"}).json()
    assert "per_sf_size_flag" not in j
    for s in j["signals"]:
        assert "size_flag_note" not in s
        assert not any(p.get("size_dissimilar") for p in (s.get("comp_points") or []))


# --- Stage 3: specialized formats (real parcels via the test route) ------------------
K5_GE5 = "1010190010"      # K5 food, >=5 same-format nearby
K7_GE5_PURE = "1012990041"  # K7 bank, >=5 same-format, pure-share (per-SF shown)
K7_LOWSHARE = "1001940038"  # K7 bank, low retail-share -> per-SF suppressed
K6_LT5 = "1000730010"       # K6 center, <5 same-format
K9_LT5 = "1000740001"       # K9 misc, <5 same-format
K8_BBL = "2045040412"       # K8 big-box (citywide)
K3_HELD = "1006460018"      # K3 dept, same-size comps found (band held)
K3_ZERO = "1004830007"      # K3 dept, zero same-size (all flagged)


def test_seek5_satisfied_discloses_5_of_8(client):
    for bbl, label in [(K5_GE5, "Food establishment"), (K7_GE5_PURE, "Bank branch")]:
        j = client.get("/api/retail_screen", params={"bbl": bbl}).json()
        assert j["status"] == "ok" and j["comp_meta"]["comp_count"] == 8
        assert j["comp_meta"]["composition"]["exact_count"] == 5            # 5 same-format kept
        assert f"5 of 8 comps are same-format ({label})" in j["retail_fallback_note"]
        assert max(r["distance_display"] and float(r["distance_display"]) for r in j["variance"]["all_diffs"]) <= 1.0                               # never past the cap


def test_seek5_under_5_fills_to_8_no_refuse(client):
    for bbl in (K6_LT5, K9_LT5):
        j = client.get("/api/retail_screen", params={"bbl": bbl}).json()
        assert j["status"] == "ok" and j["comp_meta"]["comp_count"] == 8     # filled to 8
        n = j["comp_meta"]["composition"]["exact_count"]
        assert n < 5 and f"{n} of 8 comps are same-format" in j["retail_fallback_note"]


def test_k8_citywide_no_cap_discloses_max_distance(client):
    j = client.get("/api/retail_screen", params={"bbl": K8_BBL}).json()
    assert j["status"] == "ok" and j["comp_meta"]["comp_count"] == 8
    assert j["comp_meta"]["composition"]["exact_count"] == 8                 # all same-format K8
    assert "drawn citywide" in j["retail_fallback_note"] and "furthest comp" in j["retail_fallback_note"]
    # crosses boroughs and reaches well past any local cap (no refusal for distance)
    boros = {r["parcel_id"][0] for r in j["variance"]["all_diffs"]}
    assert len(boros) >= 2
    assert max(float(r["distance_display"]) for r in j["variance"]["all_diffs"]) > 1.5


def test_k3_with_same_size_band_held_per_sf_shown(client):
    j = client.get("/api/retail_screen", params={"bbl": K3_HELD}).json()
    persf = next(s for s in j["signals"] if s["key"] == "mv_per_gross_sf")
    assert persf["refused"] is False                                        # per-SF shown
    assert j["comp_meta"]["sf_band_applied"] is True and not j.get("per_sf_size_flag")
    assert "broader retail" in j["retail_fallback_note"]                    # cross-format disclosed
    assert max(float(r["distance_display"]) for r in j["variance"]["all_diffs"]) <= 1.0


def test_k3_zero_same_size_all_flagged_not_suppressed(client):
    j = client.get("/api/retail_screen", params={"bbl": K3_ZERO}).json()
    persf = next(s for s in j["signals"] if s["key"] == "mv_per_gross_sf")
    assert persf["refused"] is False                                        # per-SF rendered, NOT suppressed
    assert j.get("per_sf_size_flag") is True
    assert "larger than surrounding retail" in j["retail_fallback_note"]
    assert "all marked size-dissimilar" in j["retail_fallback_note"]
    html = client.get("/retail_screen", params={"bbl": K3_ZERO}).text
    assert 'class="size-flag"' in html and "outlier" not in html.lower()


def test_lowshare_specialized_per_sf_suppressed(client):
    j = client.get("/api/retail_screen", params={"bbl": K7_LOWSHARE}).json()
    persf = next(s for s in j["signals"] if s["key"] == "mv_per_gross_sf")
    assert persf["refused"] is True                                         # Stage-1 gate, unchanged
    assert "blends retail with other uses" in persf["message"]


def test_specialized_still_refused_on_public_screen(client):
    for bbl in (K8_BBL, K3_ZERO, K5_GE5):
        j = client.get("/api/screen", params={"bbl": bbl}).json()
        assert j["status"] == "refused" and j["reason"] == "out_of_scope_v1"


def test_k3_quality_note_on_every_k3_top_of_result(client):
    for bbl in (K3_HELD, K3_ZERO):                              # same-size AND all-marked K3
        j = client.get("/api/retail_screen", params={"bbl": bbl}).json()
        assert "very few true comparables" in j["k3_quality_note"]
        assert "directional, not precise" in j["k3_quality_note"]
        assert j.get("retail_fallback_note")                   # mechanical notes still present
        html = client.get("/retail_screen", params={"bbl": bbl}).text
        assert html.index("k3-quality-note") < html.index('class="subject"')   # above the numbers
        assert "outlier" not in html.lower() and "flagged" not in html.lower()


def test_quality_note_only_on_k3(client):
    for bbl in (K5_GE5, K7_GE5_PURE, K6_LT5, K9_LT5, K8_BBL, PURE):
        assert "k3_quality_note" not in client.get("/api/retail_screen", params={"bbl": bbl}).json()
    assert "k3_quality_note" not in client.get("/api/screen", params={"bbl": "1013000001"}).json()


def test_public_screen_still_refuses_retail(client):
    j = client.get("/api/screen", params={"bbl": PURE}).json()
    assert j["status"] == "refused" and j["reason"] == "out_of_scope_v1"


def test_office_screen_unchanged(client):
    j = client.get("/api/screen", params={"bbl": "1013000001"}).json()
    assert j["status"] == "ok"
    assert "classification_note" not in j and "retail_fallback_note" not in j   # no retail keys leak
