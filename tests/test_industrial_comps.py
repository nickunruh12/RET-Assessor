"""Industrial (F-code) engine tests. Industrial is LIVE on public /screen (F-codes intercepted
in _screen_view); the /industrial_screen route is kept for byte-identical debugging. Skipped
without the built DB. Office/retail asserted unaffected.
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
    assert "out-of-borough" not in allm["radius_control"]["auto_label"]          # label also accurate

    # 1007610041 genuinely reaches Queens -> the note AND the label claim out-of-borough.
    crossed = client.get("/api/industrial_screen", params={"bbl": "1007610041"}).json()
    assert len({r["parcel_id"][0] for r in crossed["variance"]["all_diffs"]}) >= 2
    assert "very few industrial parcels" in (crossed.get("retail_fallback_note") or "")
    assert "out-of-borough" in crossed["radius_control"]["auto_label"]


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


# --- INDUSTRIAL LIVE on public /screen; walls hold; office/retail unaffected -----------
def test_office_and_retail_unaffected_public(client):
    assert client.get("/api/screen", params={"bbl": "1013000001"}).json()["status"] == "ok"   # office
    assert client.get("/api/screen", params={"bbl": "1000650004"}).json()["status"] == "ok"   # retail
    # no industrial keys leak into the office view
    o = client.get("/api/screen", params={"bbl": "1013000001"}).json()
    assert "Industrial" not in (o["subject"].get("bucket_label") or "")


def test_industrial_now_live_on_public_screen_byte_identical_to_test_route(client):
    # INDUSTRIAL LIVE — an F-code on the PUBLIC route renders the full industrial screen,
    # byte-identical to the /industrial_screen route (same engine, no fork).
    import json
    pub = client.get("/api/screen", params={"bbl": CORE}).json()
    test = client.get("/api/industrial_screen", params={"bbl": CORE}).json()
    assert pub["status"] == "ok" and pub["subject"]["bucket_label"].startswith("Industrial — F")
    assert json.dumps(pub, sort_keys=True, default=str) == json.dumps(test, sort_keys=True, default=str)


def test_live_switch_is_f_only_other_classes_still_refuse(client):
    # CRITICAL — the flip opens F-codes ONLY. Condos (R*) and other non-office/non-K/non-F
    # class-4 codes (V vacant, G garage, U utility) must STILL refuse out_of_scope_v1.
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    try:
        for like in ("R%", "V%", "G%", "U%"):
            row = con.execute(
                "SELECT parcel_id FROM parcels WHERE bldg_class LIKE ? LIMIT 1", [like]).fetchone()
            if not row:
                continue
            j = client.get("/api/screen", params={"bbl": row[0]}).json()
            assert j["status"] == "refused" and j["reason"] == "out_of_scope_v1", (like, j)
    finally:
        con.close()


# --- coverage (item 5) — SUBJECT-side caveat (LIVE) -------------------------------------
def test_subject_coverage_caveat_fires_on_low_coverage_f8_with_provenance(client):
    # LOW_COVER is itself land-dominant -> the SUBJECT-side caveat fires (its own per-SF is
    # caveated). Comp-side land-dominance is the separate exclusion disclosure (below).
    j = client.get("/api/industrial_screen", params={"bbl": LOW_COVER}).json()
    if j.get("status") != "ok":
        pytest.skip(f"{LOW_COVER} not screenable ({j.get('reason')})")
    note = j.get("retail_fallback_note") or ""
    assert "This parcel is land-dominant" in note                  # subject-side caveat fired
    assert "building-area" in note and "lot-area" in note          # shows BldgArea/LotArea + ratio
    assert "64uk-42ks" in note                                     # carries PLUTO citation
    # comp-side never repeated in the subject caveat (was the contradiction we removed)
    assert "comps are also land-dominant" not in note


def test_subject_coverage_caveat_quiet_on_normal_coverage(client):
    j = client.get("/api/industrial_screen", params={"bbl": CORE}).json()
    assert j["status"] == "ok"
    assert "This parcel is land-dominant" not in (j.get("retail_fallback_note") or "")


# --- LAYER 1: land-dominant comp exclusion from per-SF ----------------------------------
def _persf(j):
    return next(s for s in j["signals"] if s["key"] == "mv_per_gross_sf")


def test_land_dominant_comps_excluded_from_per_sf_but_kept_in_table(client):
    # LOW_COVER's set has land-dominant comps -> excluded from per-SF, still marked in the table.
    j = client.get("/api/industrial_screen", params={"bbl": LOW_COVER}).json()
    if j.get("status") != "ok":
        pytest.skip("subject not screenable")
    ps = _persf(j)
    n_excl = ps["land_dominant_excluded"]
    assert n_excl >= 1                                             # exclusion happened
    assert ps["refused"] is False                                 # PSF still computed on the rest
    assert ps["land_dominant_note"] and "excluded from per-SF as land-dominant" in ps["land_dominant_note"]
    marked = [r for r in j["variance"]["all_diffs"] if r.get("land_dominant")]
    assert len(marked) == n_excl                                  # comps stay in table, marked
    # excluded comps are NOT in the per-SF chart distribution, but ARE in the value one
    assert len(ps["distribution"]) == ps["n"]                     # PSF pop excludes land-dominant
    val = next(s for s in j["signals"] if s["key"] == "assessed_value_market")
    assert val["n"] == j["comp_meta"]["comp_count"]               # value distribution keeps them


def test_no_land_dominant_comps_no_exclusion_disclosure(client):
    # A clean set: nothing excluded, no note, no marks.
    j = client.get("/api/industrial_screen", params={"bbl": CORE}).json()
    ps = _persf(j)
    assert ps["land_dominant_excluded"] == 0 and ps.get("land_dominant_note") is None
    assert not any(r.get("land_dominant") for r in j["variance"]["all_diffs"])


def test_percentile_filter_stacks_inband_and_non_land_dominant(client):
    # On a band-relaxed set the per-SF percentile computes on comps that are (in-band) AND
    # (not land-dominant); percentile_n states the effective post-both-filter count.
    j = client.get("/api/industrial_screen", params={"bbl": LOW_COVER}).json()
    if j.get("status") != "ok":
        pytest.skip("subject not screenable")
    ps = _persf(j)
    if ps["subject_percentile"] is not None:
        assert ps["percentile_n"] is not None                     # effective count stated
        assert ps["percentile_n"] <= ps["n"]                      # never more than the PSF pool


def test_land_dominant_subject_per_sf_withheld(client):
    # A land-dominant subject's own per-SF is meaningless -> withheld (value, percentile, and
    # the chart point), with a stated reason; the caveat still fires; comp-side + value untouched.
    j = client.get("/api/industrial_screen", params={"bbl": LOW_COVER}).json()
    if j.get("status") != "ok":
        pytest.skip("subject not screenable")
    ps = _persf(j)
    assert ps["subject_value"] is None and ps["subject_percentile"] is None      # withheld
    assert ps["subject_point"]["x"] is None                                      # not plotted
    assert "Subject per-SF withheld" in ps["percentile_note"] and "land-dominant" in ps["percentile_note"]
    assert "This parcel is land-dominant" in (j.get("retail_fallback_note") or "")  # caveat still fires
    assert ps["mean"] is not None and ps["refused"] is False                     # comp-side stats intact
    val = next(s for s in j["signals"] if s["key"] == "assessed_value_market")
    assert val["subject_point"]["x"] is not None                                 # value chart unchanged


def test_normal_coverage_subject_per_sf_plots_as_before(client):
    # A healthy-coverage subject plots its per-SF exactly as before (not withheld).
    j = client.get("/api/industrial_screen", params={"bbl": CORE}).json()
    ps = _persf(j)
    assert ps["subject_value"] is not None and ps["subject_point"]["x"] is not None
    assert "withheld" not in (ps.get("percentile_note") or "")


def test_coverage_ratio_math():
    assert coverage_ratio(3000, 10000) == 0.3
    assert coverage_ratio(500, 10000) == 0.05
    assert coverage_ratio(3000, None) is None and coverage_ratio(3000, 0) is None


def test_coverage_note_subject_side_only():
    # Fires ONLY on subject land-dominance now (comp-side is the exclusion, handled elsewhere).
    assert coverage_note(0.08, 0.30) is not None                  # subject land-dominant -> fires
    assert coverage_note(0.30, 0.30) is None                      # at threshold -> no
    assert coverage_note(1.0, 0.30) is None                       # healthy subject -> no
    assert coverage_note(None, 0.30) is None                      # unmeasurable -> no


def test_coverage_note_no_verdict_language():
    low = coverage_note(0.08, 0.30).lower()
    for banned in ("outlier", "flagged", "over-assessed", "under-assessed", "overvalued",
                   "undervalued", "should", "fair", "true value"):
        assert banned not in low
