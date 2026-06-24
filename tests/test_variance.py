"""Variance-layer correctness + the hard no-causal-language rule."""
from datetime import date

import pytest

from screener.comps import CompRow, CompSet
from screener.schema import Citation
from screener.variance import compute_variance

# Phrases that would turn a difference into a verdict. None may appear in any output.
BANNED = ["because", "due to", "driven by", "explained by", "caused by",
          "results from", "result of", "leads to", "owing to", "thanks to",
          "as a result", "attributable to"]


def _comp(pid, curmkttot, sf, dist, bldg_class, year_built, match_type="exact"):
    return CompRow(
        citation=Citation(source_dataset="8y4t-faws", dataset_version="roll-v",
                          roll_year="2027", retrieval_date=date(2026, 6, 19), parcel_id=pid),
        bldg_class=bldg_class, bucket="O3", match_type=match_type,
        sf=sf, sf_source="pluto_bldgarea", sf_dataset_version="64uk-42ks 26v1",
        year_built=year_built, house_number="10", street_name="Broad St",
        pluto_address="10 Broad St", stories=8.0, distance_miles=dist, latitude=40.7, longitude=-74.0,
        curmkttot=curmkttot, curtxbtot=None, curtrntot=None, curacttot=None,
    )


def _subject():
    return {"parcel_id": "9999999999", "bldg_class": "O3", "sf": 10000.0,
            "year_built": "1980", "curmkttot": 1000.0}


def _compset(comps):
    return CompSet(subject_bbl="9999999999", subject=_subject(), comps=comps,
                   count=len(comps), radius_used_miles=1.0, refused=False, criteria={},
                   exact_count=len(comps), adjacent_count=0, adjacent_breakdown={})


@pytest.fixture
def res():
    comps = [
        _comp("1000000001", 1200, 12000, 0.4, "O5", "2015", match_type="adjacent"),
        _comp("1000000002", 800, 9000, 0.1, "O3", None),       # missing vintage
        _comp("1000000003", 2000, 10000, 0.9, "O3", "1990"),
    ]
    return compute_variance(_compset(comps))


def test_attribute_diff_math(res):
    by_id = {d.citation.parcel_id: d for d in res.all_diffs}
    a, b, c = by_id["1000000001"], by_id["1000000002"], by_id["1000000003"]
    assert a.assessed_pct_diff == 20.0 and a.sf_pct_diff == 20.0
    assert b.assessed_pct_diff == -20.0 and b.sf_pct_diff == -10.0
    assert c.assessed_pct_diff == 100.0 and c.sf_pct_diff == 0.0


def test_full_set_is_queryable(res):
    assert len(res.all_diffs) == 3                       # every comp present underneath


def test_nearest_by_distance_is_single_dimension(res):
    order = [d.distance_miles for d in res.views["nearest_by_distance"].rows]
    assert order == sorted(order)                        # ordered by distance only
    assert res.views["nearest_by_distance"].rows[0].citation.parcel_id == "1000000002"


def test_nearest_by_sf_is_single_dimension(res):
    rows = res.views["nearest_by_sf"].rows
    assert [r.citation.parcel_id for r in rows] == ["1000000003", "1000000002", "1000000001"]
    assert [abs(r.sf_pct_diff) for r in rows] == sorted(abs(r.sf_pct_diff) for r in rows)


def test_most_different_by_assessed_both_directions(res):
    rows = res.views["most_different_by_assessed"].rows
    assert rows[0].citation.parcel_id == "1000000003"   # +100% is the largest magnitude
    mags = [abs(r.assessed_pct_diff) for r in rows]
    assert mags == sorted(mags, reverse=True)
    # both directions retained: the set includes a higher (+) and a lower (-) comp
    signs = {(_ := r.assessed_pct_diff) and (r.assessed_pct_diff > 0) for r in rows}
    assert True in signs and False in signs


def test_year_built_shown_when_present_flagged_when_missing(res):
    by_id = {d.citation.parcel_id: d for d in res.all_diffs}
    assert by_id["1000000003"].year_built == "1990" and not by_id["1000000003"].year_built_missing
    assert by_id["1000000002"].year_built_missing
    assert "year built n/a" in by_id["1000000002"].differs_on
    assert "year built 1990 vs 1980" in by_id["1000000003"].differs_on


def test_year_built_never_used_to_sort(res):
    # None of the three views order by a vintage dimension.
    dims = {v.dimension for v in res.views.values()}
    assert all("year" not in d.lower() and "built" not in d.lower() and "vintage" not in d.lower()
               for d in dims)


def test_every_row_carries_provenance(res):
    for d in res.all_diffs:
        assert d.citation.source_dataset and d.citation.roll_year
        assert d.citation.parcel_id and d.citation.retrieval_date
        assert d.sf_dataset_version                      # PLUTO version for the SF attribute


def test_no_causal_language_anywhere(res):
    blobs = [d.differs_on for d in res.all_diffs]
    blobs += [v.name for v in res.views.values()]
    blobs.append(res.provenance["year_built_note"])
    haystack = " ".join(blobs).lower()
    hits = [w for w in BANNED if w in haystack]
    assert hits == [], f"causal language leaked: {hits}"


def test_refused_compset_yields_no_views():
    cs = CompSet("9999999999", {"parcel_id": "9999999999"}, [], 0, 1.0, True, {},
                 note="insufficient_comps_within_cap")
    r = compute_variance(cs)
    assert r.refused and r.all_diffs == [] and r.views == {}
