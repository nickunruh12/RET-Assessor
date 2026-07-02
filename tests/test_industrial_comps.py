"""Industrial (F-code) engine tests. Reachable via the /industrial_screen TEST routes only
(F is NOT public yet). Skipped without the built DB. Office/retail asserted unaffected.
"""
import warnings

import duckdb
import pytest

from screener import config
from screener.industrial_comps import coverage_note, coverage_ratio

warnings.filterwarnings("ignore")
pytestmark = pytest.mark.skipif(not config.DB_PATH.exists(), reason="screener.duckdb not built")

CORE = "3022210014"       # Brooklyn F5, dense cluster -> same-subcode in-band, band held
MANHATTAN = "1019980016"  # Manhattan F2 -> reaches out-of-borough citywide
BIGBOX = "4002940106"     # F1 654,615 SF -> big-box citywide-by-size
ISOLATED = "5041910038"   # F5 with 0 F-neighbors within the cap -> refuses
LOW_COVER = "2025990090"  # F8 tank/utility-yard, coverage ~0.00 -> land-dominant disclosure fires


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from screener.api import app
    return TestClient(app)


def _persf(j):
    return next(s for s in j["signals"] if s["key"] == "mv_per_gross_sf")


# --- routing + full screen -----------------------------------------------------------
def test_core_industrial_full_screen_same_subcode(client):
    j = client.get("/api/industrial_screen", params={"bbl": CORE}).json()
    assert j["status"] == "ok"
    assert [s["key"] for s in j["signals"]] == ["assessed_value_market", "tax_bill", "mv_per_gross_sf"]
    assert j["subject"]["bucket_label"].startswith("Industrial — F")
    assert j["comp_meta"]["comp_count"] >= 8
    assert j["comp_meta"]["composition"]["exact_count"] >= 1        # same-subcode comps present
    assert j["comp_meta"]["radius_used_miles"] <= 1.75              # never past the cap
    assert _persf(j)["refused"] is False                           # per-SF shown for industrial
    assert j["radius_control"]["auto_label"] == "Auto — expands up to 1.75 mi"


def test_industrial_per_sf_and_provenance_present(client):
    j = client.get("/api/industrial_screen", params={"bbl": CORE}).json()
    assert j["provenance"]["source_dataset"] == "8y4t-faws"        # full citation tuple
    sig = _persf(j)
    assert len(sig["distribution"]) == sig["n"]


def test_manhattan_reaches_cross_borough_with_disclosure(client):
    j = client.get("/api/industrial_screen", params={"bbl": MANHATTAN}).json()
    assert j["status"] == "ok" and j["comp_meta"]["comp_count"] >= 8
    assert "reaches" in j["radius_control"]["auto_label"] or "out-of-borough" in j["radius_control"]["auto_label"]
    assert j["retail_fallback_note"] and "other boroughs" in j["retail_fallback_note"]
    assert j["cross_borough_note"]                                 # existing machinery also discloses


def test_manhattan_note_gated_on_actual_cross_borough(client):
    # The Manhattan cross-borough note must fire ONLY when a comp truly left the borough.
    # 1007880016's citywide-nearest step lands an all-Manhattan cluster -> must NOT claim
    # "other boroughs" (and the shared cross-borough note is correctly silent too).
    allm = client.get("/api/industrial_screen", params={"bbl": "1007880016"}).json()
    assert allm["status"] == "ok"
    assert {r["parcel_id"][0] for r in allm["variance"]["all_diffs"]} == {"1"}   # never left Manhattan
    assert "very few industrial parcels" not in (allm.get("retail_fallback_note") or "")
    assert not allm.get("cross_borough_note")                                    # consistent

    # 1007610041 genuinely reaches Queens -> the note fires.
    crossed = client.get("/api/industrial_screen", params={"bbl": "1007610041"}).json()
    assert len({r["parcel_id"][0] for r in crossed["variance"]["all_diffs"]}) >= 2
    assert "very few industrial parcels" in (crossed.get("retail_fallback_note") or "")


def test_bigbox_citywide_few_peers_disclosure(client):
    j = client.get("/api/industrial_screen", params={"bbl": BIGBOX}).json()
    assert j["status"] == "ok" and j["comp_meta"]["comp_count"] == 8
    assert j["radius_control"]["auto_label"] == "Citywide — nearest big-box industrial comps, no distance cap"
    q = j["k3_quality_note"]                                        # reuses the prominent-note slot
    assert q and "few true peers" in q and "directional, not precise" in q
    assert "furthest comp" in q                                    # max comp distance disclosed
    assert j["comp_meta"]["radius_used_miles"] > 1.75              # no distance cap for big-box
    assert _persf(j)["subject_percentile"] is not None            # big-box keeps its per-SF percentile


def test_isolated_industrial_refuses_not_reaches_past_cap(client):
    j = client.get("/api/industrial_screen", params={"bbl": ISOLATED}).json()
    assert j["status"] == "refused" and j["reason"] == "insufficient_comps_within_cap"
    assert j.get("candidates_within_cap", 0) < 8                   # did not reach past the 1.75 cap


# --- walls: office/retail unaffected; F NOT public yet -------------------------------
def test_office_and_retail_unaffected_public(client):
    assert client.get("/api/screen", params={"bbl": "1013000001"}).json()["status"] == "ok"   # office
    assert client.get("/api/screen", params={"bbl": "1000650004"}).json()["status"] == "ok"   # retail
    # no industrial keys leak into the office view
    o = client.get("/api/screen", params={"bbl": "1013000001"}).json()
    assert "Industrial" not in (o["subject"].get("bucket_label") or "")


def test_industrial_not_live_on_public_screen_yet(client):
    # F still refuses out_of_scope on the PUBLIC route (no _screen_view interception yet).
    j = client.get("/api/screen", params={"bbl": CORE}).json()
    assert j["status"] == "refused" and j["reason"] == "out_of_scope_v1"


def test_condo_and_other_out_of_scope_still_refuse(client):
    for bbl in ("3024131120",):                                    # RG condo
        j = client.get("/api/screen", params={"bbl": bbl}).json()
        assert j["status"] == "refused" and j["reason"] == "out_of_scope_v1"


# --- coverage (item 5) — now LIVE (PLUTO LotArea loaded) --------------------------------
def test_coverage_disclosure_fires_on_low_coverage_f8_with_provenance(client):
    j = client.get("/api/industrial_screen", params={"bbl": LOW_COVER}).json()
    if j.get("status") != "ok":
        pytest.skip(f"{LOW_COVER} not screenable ({j.get('reason')})")
    note = j.get("retail_fallback_note") or ""
    assert "Land-dominant" in note                                 # disclosure fired
    assert "building-area" in note and "lot-area" in note          # shows BldgArea/LotArea + ratio
    assert "64uk-42ks" in note                                     # carries PLUTO citation


def test_coverage_disclosure_quiet_on_normal_coverage(client):
    # A dense same-subcode F5 cluster (band held, ~1.0 coverage) must NOT fire land-dominant.
    j = client.get("/api/industrial_screen", params={"bbl": CORE}).json()
    assert j["status"] == "ok"
    assert "Land-dominant" not in (j.get("retail_fallback_note") or "")


def test_coverage_ratio_math():
    assert coverage_ratio(3000, 10000) == 0.3
    assert coverage_ratio(500, 10000) == 0.05
    assert coverage_ratio(3000, None) is None and coverage_ratio(3000, 0) is None


def test_coverage_note_fires_on_subject_or_two_comps():
    # subject land-dominant -> fires
    assert coverage_note(0.08, [1.0, 1.2, 0.9], 0.30) is not None
    # 2+ land-dominant comps -> fires
    assert coverage_note(1.0, [0.2, 0.25, 1.1], 0.30) is not None
    # only one low comp, healthy subject -> does not fire
    assert coverage_note(1.0, [0.2, 1.1, 1.2], 0.30) is None
    # all healthy -> None
    assert coverage_note(1.0, [1.0, 1.1], 0.30) is None


def test_coverage_note_no_verdict_language():
    note = coverage_note(0.08, [], 0.30)
    low = note.lower()
    for banned in ("outlier", "flagged", "over-assessed", "under-assessed", "overvalued",
                   "undervalued", "should", "fair", "true value"):
        assert banned not in low
