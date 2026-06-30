"""Retail classifier (Stage 1) unit tests. Fixtures are REAL class-4 K parcels with their
ACTUAL PLUTO floor-area values (BBL + address recorded) — not synthesized. Office is not
touched by this module; a separate test confirms office screening is unchanged.

Each fixture: (bbl, address, k_code, bldgarea, retailarea, officearea, resarea).
"""
import pytest

from screener.retail import (
    PURE_RETAIL,
    RETAIL_OFFICE,
    RETAIL_OTHER,
    RETAIL_RESIDENTIAL,
    classify_retail,
)

# --- real parcels, real PLUTO areas (pulled from 64uk-42ks joined to the class-4 roll) ----
K4_PURE = ("1000200012", "47 BROADWAY", "K4", 27640, 27640, 0, 0)
K2_OFFICE = ("1000630018", "179 BROADWAY", "K2", 13820, 2500, 9056, 0)
K4_OFFICE = ("1000070028", "28 WATER STREET", "K4", 4104, 3078, 1026, 0)
K4_RESID = ("1000100032", "6 STONE STREET", "K4", 9075, 5601, 0, 3474)
K4_OTHER = ("1000200013", "49 BROADWAY", "K4", 17250, 7375, 0, 0)
K1_PURE = ("1000640002", "22 MAIDEN LANE", "K1", 531, 531, 0, 0)
K5_FOOD = ("1000700020", "212 PEARL STREET", "K5", 1450, 1450, 0, 0)
K7_EMBEDDED = ("1001940038", "407 BROADWAY", "K7", 15914, 7500, 8414, 0)
K4_BOTH = ("1000070031", "105 BROAD STREET", "K4", 7475, 2990, 1495, 2990)
MISSING_RET = ("1003530075", "140 DELANCEY STREET", "K4", 20000, None, None, None)


def _classify(fx):
    _bbl, _addr, code, ba, ret, off, res = fx
    return classify_retail(code, ba, ret, off, res, pluto_version="PLUTO 26v1")


# --- core routing --------------------------------------------------------------------
def test_k4_pure_high_retail_share():
    c = _classify(K4_PURE)
    assert c.category == PURE_RETAIL and c.per_sf_shown is True
    assert c.retail_share == 1.0
    assert c.note == "Coded K4 (mixed-use) but >=80% retail by floor area; screened as pure retail."


def test_k2_office_mixed_fires_k2_note():
    c = _classify(K2_OFFICE)              # 2500/13820 = 0.18 retail; 9056/13820 = 0.66 office
    assert c.category == RETAIL_OFFICE and c.per_sf_shown is False
    assert "Coded K2 (multi-store retail)" in c.note and "retail + office" in c.note


def test_k4_office():
    c = _classify(K4_OFFICE)              # 3078/4104 = 0.75 retail; 1026/4104 = 0.25 office
    assert c.category == RETAIL_OFFICE and c.per_sf_shown is False
    assert "Coded K4" in c.note and "retail + office" in c.note


def test_k4_residential():
    c = _classify(K4_RESID)               # 5601/9075 = 0.62 retail; office 0; 3474/9075 = 0.38 res
    assert c.category == RETAIL_RESIDENTIAL and c.per_sf_shown is False
    assert "retail + residential" in c.note


def test_k4_other_second_use():
    c = _classify(K4_OTHER)               # 7375/17250 = 0.43 retail; no office, no res >=10%
    assert c.category == RETAIL_OTHER and c.per_sf_shown is False
    assert "retail + other use" in c.note


def test_k1_pure_no_note():
    c = _classify(K1_PURE)                # 531/531 = 1.0
    assert c.category == PURE_RETAIL and c.per_sf_shown is True and c.note is None


# --- specialized formats: category by K-code, per-SF by share alone ------------------
def test_k5_food_pure_per_sf_true():
    c = _classify(K5_FOOD)                # 1450/1450 = 1.0 -> per-SF shown
    assert c.category == "K5_food" and c.per_sf_shown is True and c.note is None


def test_k7_bank_embedded_per_sf_false():
    c = _classify(K7_EMBEDDED)            # 7500/15914 = 0.47 retail -> per-SF refused
    assert c.category == "K7_bank" and c.per_sf_shown is False and c.note is None


# --- office-precedence + edge cases --------------------------------------------------
def test_office_precedence_when_both_office_and_residential():
    c = _classify(K4_BOTH)                # office 0.20 AND res 0.40, both >= 0.10 -> office wins
    assert c.category == RETAIL_OFFICE


def test_missing_retailarea_defaults_to_other_never_pure():
    c = _classify(MISSING_RET)           # retailarea null -> conservative mixed
    assert c.category == RETAIL_OTHER and c.per_sf_shown is False and c.retail_share is None
    assert "could not be measured" in c.note
    assert c.category != PURE_RETAIL     # never guess pure when unmeasurable


def test_retailarea_exceeds_bldgarea_routes_conservative_not_pure():
    # adversarial 1b: corrupt PLUTO areas (retail 1500 > gross 1000) must NOT route pure or
    # show per-SF; conservative mixed bucket with the validation note, share not >100%.
    c = classify_retail("K4", 1000, 1500, 0, 0, pluto_version="PLUTO 26v1")
    assert c.category == RETAIL_OTHER and c.per_sf_shown is False
    assert c.category != PURE_RETAIL
    assert c.retail_share is None                       # no >100% share produced
    assert "failed validation" in c.note and "component area exceeds gross" in c.note


def test_component_areas_summing_past_gross_flagged():
    # retail+office+res = 1.3x gross -> data error -> conservative
    c = classify_retail("K2", 1000, 600, 500, 200)
    assert c.category == RETAIL_OTHER and c.per_sf_shown is False and c.retail_share is None
    assert "failed validation" in c.note


def test_specialized_bad_area_not_shown_per_sf():
    # a specialized parcel with corrupt areas must also not show per-SF on bad data
    c = classify_retail("K7", 1000, 2000, 0, 0)
    assert c.per_sf_shown is False and c.category == RETAIL_OTHER and "failed validation" in c.note


def test_valid_areas_within_tolerance_unaffected():
    # legitimate full-retail parcel (retail == gross) still classifies pure, no false positive
    c = classify_retail("K1", 1000, 1000, 0, 0)
    assert c.category == PURE_RETAIL and c.per_sf_shown is True and c.note is None


def test_bldgarea_zero_is_unmeasurable():
    c = classify_retail("K4", 0, 1000, 0, 0, pluto_version="PLUTO 26v1")
    assert c.category == RETAIL_OTHER and c.per_sf_shown is False and c.retail_share is None


def test_threshold_is_named_config_and_overridable():
    # at the boundary: 0.80 share is pure with default; tightening the threshold flips it
    c_default = classify_retail("K1", 1000, 800, 0, 200)               # share 0.80
    assert c_default.category == PURE_RETAIL and c_default.per_sf_shown is True
    c_strict = classify_retail("K1", 1000, 800, 0, 200, pure_threshold=0.85)
    assert c_strict.category != PURE_RETAIL and c_strict.per_sf_shown is False


def test_provenance_cites_pluto():
    c = _classify(K4_PURE)
    assert c.provenance["source_dataset"] == "64uk-42ks"
    assert c.provenance["dataset_version"] == "PLUTO 26v1"
    assert "retailarea / bldgarea" in c.provenance["derived"]


def test_no_verdict_language_in_notes():
    for fx in (K4_PURE, K2_OFFICE, K4_OFFICE, K4_RESID, K4_OTHER, MISSING_RET):
        note = (_classify(fx).note or "").lower()
        for banned in ("overpriced", "underpriced", "too high", "too low", "should",
                       "over-assessed", "under-assessed", "outlier"):
            assert banned not in note
