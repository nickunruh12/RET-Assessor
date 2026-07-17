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

CORE = "3022210014"       # Brooklyn F5, dense cluster -> same-subcode in-band within standard cap
LARGE = "4002940106"      # F1 654,615 SF -> fills LOCALLY (~0.7mi); no big-box branch, no extension
EXTEND = "3017200001"     # F5 574,055 SF -> shortfall extends past 1.75mi to ~2.0mi
ISOLATED = "1019530042"   # E1 500 SF -> can't field 8 in-band even at 4.0mi -> refuses
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
    assert [s["key"] for s in j["signals"]] == ["assessed_value_market", "mv_per_gross_sf", "tax_bill", "tax_per_gross_sf"]
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


def test_no_big_box_branch_large_subject_fills_locally(client):
    # The 100K big-box citywide branch is GONE. A 654K subject fills locally within the standard
    # cap — no "few true peers" note, no citywide-no-cap label, and it never extends.
    j = client.get("/api/industrial_screen", params={"bbl": LARGE}).json()
    assert j["status"] == "ok" and j["comp_meta"]["comp_count"] >= 8
    assert j["comp_meta"]["radius_used_miles"] <= 1.75            # fills locally, no extension
    assert not j.get("k3_quality_note")                          # no prominent "few peers" note
    html = client.get("/screen", params={"bbl": LARGE}).text
    assert "few true peers" not in html.lower() and "big-box" not in html.lower()
    assert "reached beyond" not in html                          # did not extend


def test_shortfall_extension_fires_and_discloses(client):
    # A subject short of 8 in-band comps at 1.75mi extends to the 4.0mi cap at the SAME band and
    # states the actual radius reached. Band is NEVER widened (sf_band_relaxed stays False).
    j = client.get("/api/industrial_screen", params={"bbl": EXTEND}).json()
    assert j["status"] == "ok" and j["comp_meta"]["comp_count"] >= 8
    ru = j["comp_meta"]["radius_used_miles"]
    assert 1.75 < ru <= 4.0                                      # extended into the tail, bounded
    assert j["comp_meta"]["sf_band_relaxed"] is False            # same ±75% band, no widening
    assert "reached" in j["radius_control"]["auto_label"] and "beyond" in j["radius_control"]["auto_label"]
    html = client.get("/screen", params={"bbl": EXTEND}).text
    assert "reached beyond the standard" in html and f"{ru:.1f} miles" in html
    assert "big-box" not in html.lower() and "few true peers" not in html.lower()


def test_isolated_industrial_refuses_within_extended_cap(client):
    # Genuinely peerless subject: can't field 8 in-band comps even at the 4.0mi extension -> refuse.
    j = client.get("/api/industrial_screen", params={"bbl": ISOLATED}).json()
    assert j["status"] == "refused" and j["reason"] == "insufficient_comps_within_cap"
    assert j.get("candidates_within_cap", 0) < 8                 # did not reach 8 even extended


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


def test_live_switch_is_ef_only_other_classes_still_refuse(client):
    # CRITICAL — the pooled route opens E- AND F-codes. Condos (R*) and other
    # non-office/non-K/non-E/non-F class-4 codes (V vacant, G garage, U utility) must STILL
    # refuse out_of_scope_v1.
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


# --- pooled E+F route (restructured 2026-07-17) ----------------------------------------
def _first(con, where):
    r = con.execute(f"SELECT parcel_id FROM parcels WHERE {where} AND curmkttot>0 AND sf>0 "
                    "AND pluto_latitude IS NOT NULL ORDER BY parcel_id LIMIT 1").fetchone()
    return r[0] if r else None


def test_e_codes_now_in_scope_and_route_to_industrial(client):
    # E1/E2/E9 warehouses now screen (pooled with F), product label "Industrial".
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    try:
        for sub in ("E1", "E2", "E9"):
            b = _first(con, f"bldg_class='{sub}'")
            j = client.get("/api/screen", params={"bbl": b}).json()
            assert j["status"] == "ok", (sub, j.get("reason"))
            assert j["product_label"] == "Industrial"
            assert j["subject"]["bucket_label"].startswith(f"Industrial — {sub} (")
    finally:
        con.close()


def test_e7_self_storage_walled_same_subcode_only(client):
    # E7 comps against E7 ONLY (never the pool); product label "Self-Storage"; refuses when
    # it cannot field 8 E7 comps.
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    try:
        e7s = [r[0] for r in con.execute(
            "SELECT parcel_id FROM parcels WHERE bldg_class='E7' AND curmkttot>0 AND sf>0 "
            "AND pluto_latitude IS NOT NULL ORDER BY parcel_id LIMIT 10").fetchall()]
        filled = 0
        for b in e7s:
            j = client.get("/api/screen", params={"bbl": b}).json()
            if j["status"] == "refused":
                assert j["reason"] == "insufficient_comps_within_cap"
                continue
            filled += 1
            assert j["product_label"] == "Self-Storage"
            assert j["subject"]["bucket_label"].startswith("Self-Storage — E7 (")
            comp_bbls = [r["parcel_id"] for v in j["variance"]["views"] for r in v["rows"]]
            ph = ",".join(["?"] * len(comp_bbls))
            classes = {x[0] for x in con.execute(
                f"SELECT DISTINCT bldg_class FROM parcels WHERE parcel_id IN ({ph})", comp_bbls).fetchall()}
            assert classes <= {"E7"}, f"E7 wall leaked: {classes}"
        assert filled >= 1                       # E7 fills in dense clusters (98% do now)
        # E7 refusal still happens for genuinely isolated parcels (measured ~2%): the wall means
        # it never borrows non-E7 comps to avoid refusing.
        iso = client.get("/api/screen", params={"bbl": "5032230006"}).json()
        assert iso["status"] == "refused" and iso["reason"] == "insufficient_comps_within_cap"
    finally:
        con.close()


def test_composition_note_names_subcodes_when_mixed(client):
    # A pooled subject with a cross-subcode set names the mix; a pure set says nothing.
    # 2025950039 (F8) falls back to the pool -> mixed set -> named composition.
    h = client.get("/screen", params={"bbl": "2025950039"}).text
    assert "spans multiple industrial subcodes" in h
    assert "not a value boundary" in h          # honest framing, no verdict
    # named with cleaned labels + DOF subcode
    assert "Warehouse" in h and "(" in h


def test_f8_subject_falls_back_to_pool(client):
    # An F8 tank-farm SUBJECT screens (falls back to the flat pool); its own per-SF is
    # withheld when land-dominant, but the value/tax distribution still renders.
    j = client.get("/api/screen", params={"bbl": "2025950039"}).json()
    assert j["status"] == "ok"
    assert j["comp_meta"]["comp_count"] >= config.MIN_COMP_COUNT


def test_pooled_office_retail_byte_identical(client):
    # The pooled restructure must not move office or retail at all.
    import json
    for b in ("1013010001", "1000650004"):
        j = client.get("/api/screen", params={"bbl": b}).json()
        assert j["status"] == "ok"
        assert "Industrial" not in (j["subject"].get("bucket_label") or "")
        assert "product_label" not in j       # industrial-only field never leaks


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
