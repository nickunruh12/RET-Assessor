"""Stats-layer correctness. The synthetic cases are hand-computable so the math is
pinned exactly; the DB-backed cases confirm the per-signal refusal wiring.
"""
import math
from datetime import date

import pytest

from screener.comps import CompRow, CompSet
from screener.jurisdiction import CompCriteria
from screener.schema import Citation
from screener.stats import compute_stats


def _comp(parcel_id, curmkttot, sf=10000.0, curtxbtot=None, curtrntot=None,
          curacttot=None, match_type="exact", bldg_class="O1"):
    return CompRow(
        citation=Citation(source_dataset="8y4t-faws", dataset_version="v", roll_year="2027",
                          retrieval_date=date(2026, 6, 19), parcel_id=parcel_id),
        bldg_class=bldg_class, bucket="O1", match_type=match_type,
        sf=sf, sf_source="pluto_bldgarea", sf_dataset_version="64uk-42ks 26v1",
        year_built="1980", house_number="1", street_name="Main St",
        pluto_address="1 Main St", stories=5.0, distance_miles=0.1, latitude=40.7, longitude=-74.0,
        curmkttot=curmkttot, curtxbtot=curtxbtot, curtrntot=curtrntot, curacttot=curacttot,
    )


def _compset(comps, subject, exact_count=None):
    return CompSet(
        subject_bbl=subject["parcel_id"], subject=subject, comps=comps, count=len(comps),
        radius_used_miles=0.5, refused=False, criteria={},
        exact_count=exact_count if exact_count is not None else len(comps),
        adjacent_count=0, adjacent_breakdown={},
    )


@pytest.fixture
def crit():
    return CompCriteria.load()


def test_assessed_value_math_is_exact(crit):
    comps = [_comp(f"100000000{i}", v) for i, v in enumerate([100, 200, 300, 400, 500])]
    subject = {"parcel_id": "9999999999", "curmkttot": 350, "curtxbtot": None,
               "curtrntot": None, "curacttot": None, "sf": 10000.0}
    sig = compute_stats(_compset(comps, subject), crit).signals["assessed_value_market"]
    assert sig.n == 5 and sig.excluded_blank == 0
    assert sig.mean == 300 and sig.median == 300 and sig.minimum == 100 and sig.maximum == 500
    assert math.isclose(sig.stddev, math.sqrt(20000))            # population stddev
    # subject 350: strictly below = {100,200,300} = 3 -> 60th percentile
    assert sig.subject_percentile == 60.0


def test_blanks_excluded_and_counted(crit):
    comps = [_comp("1000000001", 100), _comp("1000000002", None), _comp("1000000003", 300)]
    subject = {"parcel_id": "9999999999", "curmkttot": 200, "curtxbtot": None,
               "curtrntot": None, "curacttot": None, "sf": 10000.0}
    sig = compute_stats(_compset(comps, subject), crit).signals["assessed_value_market"]
    assert sig.n == 2 and sig.excluded_blank == 1          # blank excluded AND counted
    assert sig.mean == 200 and sig.minimum == 100 and sig.maximum == 300


def test_subject_value_not_in_distribution(crit):
    # The subject's own value must not change n or the comp distribution.
    comps = [_comp("1000000001", 100), _comp("1000000002", 300)]
    subject = {"parcel_id": "9999999999", "curmkttot": 100, "curtxbtot": None,
               "curtrntot": None, "curacttot": None, "sf": 10000.0}
    sig = compute_stats(_compset(comps, subject), crit).signals["assessed_value_market"]
    assert sig.n == 2                                      # only comps, never the subject
    assert sig.subject_percentile == 0.0                  # nothing strictly below 100


def test_tax_bill_uses_rate(crit):
    comps = [_comp("1000000001", 1_000_000, curtxbtot=700_000),
             _comp("1000000002", 2_000_000, curtxbtot=1_400_000)]
    subject = {"parcel_id": "9999999999", "curmkttot": 1_500_000, "curtxbtot": 1_000_000,
               "curtrntot": None, "curacttot": None, "sf": 10000.0}
    sig = compute_stats(_compset(comps, subject), crit).signals["tax_bill"]
    assert math.isclose(sig.minimum, 700_000 * crit.class4_tax_rate)
    assert math.isclose(sig.subject_value, 1_000_000 * crit.class4_tax_rate)


def test_psf_refuses_when_subject_has_no_sf(crit):
    comps = [_comp("1000000001", 1_000_000, sf=10000.0, curtxbtot=700_000)]
    subject = {"parcel_id": "9999999999", "curmkttot": 1_000_000, "curtxbtot": 500_000,
               "curtrntot": None, "curacttot": None, "sf": None}
    res = compute_stats(_compset(comps, subject), crit)
    assert res.signals["mv_per_gross_sf"].refused
    assert res.signals["mv_per_gross_sf"].refusal_reason == "subject_no_gross_building_area"
    # the other two still compute
    assert not res.signals["assessed_value_market"].refused
    assert not res.signals["tax_bill"].refused


def test_low_exact_caution_fires_below_threshold(crit):
    comps = [_comp(f"100000000{i}", 100 + i, match_type=("exact" if i < 2 else "adjacent"))
             for i in range(8)]
    subject = {"parcel_id": "9999999999", "curmkttot": 150, "curtxbtot": None,
               "curtrntot": None, "curacttot": None, "sf": 10000.0}
    res = compute_stats(_compset(comps, subject, exact_count=2), crit)  # 2 < 3
    assert res.low_exact_caution and "adjacent-class" in res.caution_message


def test_refused_compset_yields_no_signals(crit):
    cs = CompSet("9999999999", {"parcel_id": "9999999999"}, [], 0, 1.0, True, {},
                 note="insufficient_comps_within_cap")
    res = compute_stats(cs, crit)
    assert res.refused and res.signals == {}
