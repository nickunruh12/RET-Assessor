"""Comp-selection invariants for the office / distance / radius-first model.

Skipped if the DuckDB isn't built. Selection contract only — no statistics.
"""
import duckdb
import pytest

from screener import config
from screener.comps import select_comps
from screener.jurisdiction import CompCriteria, get_jurisdiction

pytestmark = pytest.mark.skipif(
    not config.DB_PATH.exists(), reason="screener.duckdb not built; run loader + pluto first"
)

OFFICE_DENSE = "1000090001"     # O4 Manhattan — succeeds at 0.5 mi (~28 comps)
OFFICE_EXPAND = "1000100015"    # O6 Manhattan — succeeds via expansion (~0.6 mi)
OFFICE_ISOLATED = "1000580001"  # O4 ~8.97M SF — no in-band peers, refuses
NON_OFFICE = "3000250001"       # K4 store — out of scope for v1


@pytest.fixture(scope="module")
def setup():
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    crit = CompCriteria.load()
    juris = get_jurisdiction(crit.jurisdiction)
    yield con, juris, crit
    con.close()


def test_config_loads_office_distance_model():
    c = CompCriteria.load()
    assert c.sf_band == 0.50
    assert c.activated_products == ["O"]
    assert c.radius_start_miles == 0.5 and c.radius_cap_miles == 1.0
    assert c.office_buckets["O5"] == c.office_buckets["O6"]      # grouped
    assert c.office_buckets["O7"] == c.office_buckets["O9"]      # grouped
    assert c.office_buckets["O1"] != c.office_buckets["O2"]      # exact


def test_non_office_subject_is_out_of_scope(setup):
    con, juris, crit = setup
    cs = select_comps(con, NON_OFFICE, juris, crit)
    assert cs.refused and cs.note == "out_of_scope_v1" and cs.count == 0


def test_subject_not_found(setup):
    con, juris, crit = setup
    cs = select_comps(con, "9999999999", juris, crit)
    assert cs.note == "subject_not_found"


def test_dense_office_succeeds_within_start_radius(setup):
    con, juris, crit = setup
    cs = select_comps(con, OFFICE_DENSE, juris, crit)
    assert not cs.refused
    assert cs.count >= crit.min_comp_count
    assert cs.radius_used_miles <= crit.radius_start_miles


def test_expansion_radius_between_start_and_cap(setup):
    con, juris, crit = setup
    cs = select_comps(con, OFFICE_EXPAND, juris, crit)
    assert not cs.refused
    assert crit.radius_start_miles < cs.radius_used_miles <= crit.radius_cap_miles


def test_isolated_office_refuses_with_radius_cap(setup):
    con, juris, crit = setup
    cs = select_comps(con, OFFICE_ISOLATED, juris, crit)
    assert cs.refused and cs.note == "insufficient_comps_within_cap"
    assert cs.radius_used_miles == crit.radius_cap_miles


def test_all_comps_within_radius_and_sorted(setup):
    con, juris, crit = setup
    cs = select_comps(con, OFFICE_DENSE, juris, crit)
    dists = [c.distance_miles for c in cs.comps]
    assert dists == sorted(dists)
    assert all(d <= cs.radius_used_miles + 1e-9 for d in dists)


def test_all_comps_share_bucket_and_sf_band(setup):
    con, juris, crit = setup
    cs = select_comps(con, OFFICE_DENSE, juris, crit)
    subj_bucket = cs.subject["bucket"]
    sf = cs.subject["sf"]
    lo, hi = sf * (1 - crit.sf_band), sf * (1 + crit.sf_band)
    assert all(c.bucket == subj_bucket for c in cs.comps)
    assert all(lo <= c.sf <= hi for c in cs.comps)


def test_comps_exclude_subject_and_condos(setup):
    con, juris, crit = setup
    cs = select_comps(con, OFFICE_DENSE, juris, crit)
    for c in cs.comps:
        assert c.citation.parcel_id != OFFICE_DENSE
        assert not (c.bldg_class or "").startswith("R")
        assert int(c.citation.parcel_id[6:10]) < crit.condo_unit_lot_min


def test_every_comp_carries_provenance_and_sf_version(setup):
    con, juris, crit = setup
    cs = select_comps(con, OFFICE_DENSE, juris, crit)
    assert cs.count > 0
    for c in cs.comps:
        assert c.citation.source_dataset and c.citation.roll_year
        assert c.citation.parcel_id and c.citation.retrieval_date
        # SF value cites its source per the $/SF output contract.
        if c.sf_source == "pluto_bldgarea":
            assert c.sf_dataset_version and "64uk-42ks" in c.sf_dataset_version


def test_o5_and_o6_cross_match(setup):
    con, juris, crit = setup
    # An O5 or O6 subject's comps may include both O5 and O6 (grouped bucket).
    cs = select_comps(con, OFFICE_EXPAND, juris, crit)  # O6 subject
    classes = {c.bldg_class for c in cs.comps}
    assert classes.issubset({"O5", "O6"})
