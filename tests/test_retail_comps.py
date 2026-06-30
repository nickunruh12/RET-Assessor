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


def test_public_screen_still_refuses_retail(client):
    j = client.get("/api/screen", params={"bbl": PURE}).json()
    assert j["status"] == "refused" and j["reason"] == "out_of_scope_v1"


def test_office_screen_unchanged(client):
    j = client.get("/api/screen", params={"bbl": "1013000001"}).json()
    assert j["status"] == "ok"
    assert "classification_note" not in j and "retail_fallback_note" not in j   # no retail keys leak
