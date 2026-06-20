"""Comp-selection invariants. Skipped if the DuckDB isn't built.

These assert the *selection* contract only — no statistics are computed or tested.
"""
import duckdb
import pytest

from screener import config
from screener.comps import select_comps
from screener.jurisdiction import CompCriteria, get_jurisdiction

pytestmark = pytest.mark.skipif(
    not config.DB_PATH.exists(), reason="screener.duckdb not built; run loader + pluto first"
)

MANHATTAN_OFFICE = "1002230035"  # O1, ZIP 10013
ISOLATED_TOWER = "1000580001"    # O4, ~8.97M SF — no in-band peers in its ZIP


@pytest.fixture(scope="module")
def setup():
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    crit = CompCriteria.load()
    juris = get_jurisdiction(crit.jurisdiction)
    yield con, juris, crit
    con.close()


def test_config_loads_and_validates():
    crit = CompCriteria.load()
    assert crit.sf_band == 0.50
    assert crit.class_match_level in ("letter", "exact")
    assert crit.jurisdiction == "nyc"


def test_comp_set_excludes_subject(setup):
    con, juris, crit = setup
    cs = select_comps(con, MANHATTAN_OFFICE, juris, crit)
    assert all(c.citation.parcel_id != MANHATTAN_OFFICE for c in cs.comps)


def test_every_comp_within_sf_band(setup):
    con, juris, crit = setup
    cs = select_comps(con, MANHATTAN_OFFICE, juris, crit)
    sf = cs.subject["sf"]
    lo, hi = sf * (1 - crit.sf_band), sf * (1 + crit.sf_band)
    assert all(lo <= c.sf <= hi for c in cs.comps)


def test_every_comp_same_group_and_location(setup):
    con, juris, crit = setup
    cs = select_comps(con, MANHATTAN_OFFICE, juris, crit)
    subj_group = cs.subject["class_group"]
    assert all(c.class_group == subj_group for c in cs.comps)
    assert all(c.borough == "Manhattan" for c in cs.comps)
    assert all(c.zip_code == cs.subject["zip_code"] for c in cs.comps)


def test_no_condo_unit_lots_in_comps(setup):
    con, juris, crit = setup
    cs = select_comps(con, MANHATTAN_OFFICE, juris, crit)
    for c in cs.comps:
        assert not (c.bldg_class or "").startswith("R")
        lot = int(c.citation.parcel_id[6:10])
        assert lot < crit.condo_unit_lot_min


def test_every_comp_carries_provenance(setup):
    con, juris, crit = setup
    cs = select_comps(con, MANHATTAN_OFFICE, juris, crit)
    assert cs.count > 0
    for c in cs.comps:
        # Citation construction already enforces the tuple; assert it's populated.
        assert c.citation.source_dataset and c.citation.roll_year
        assert c.citation.parcel_id and c.citation.retrieval_date


def test_isolated_parcel_returns_zero(setup):
    con, juris, crit = setup
    cs = select_comps(con, ISOLATED_TOWER, juris, crit)
    assert cs.count == 0


def test_subject_not_found_is_noted(setup):
    con, juris, crit = setup
    cs = select_comps(con, "9999999999", juris, crit)
    assert cs.count == 0 and cs.note == "subject_not_found"


def test_exact_match_level_narrows_set(setup):
    con, juris, _ = setup
    letter = CompCriteria.load()
    letter.class_match_level = "letter"
    exact = CompCriteria.load()
    exact.class_match_level = "exact"
    n_letter = select_comps(con, MANHATTAN_OFFICE, juris, letter).count
    n_exact = select_comps(con, MANHATTAN_OFFICE, juris, exact).count
    # O1-only (exact) must be a subset of all-O* (letter).
    assert n_exact <= n_letter
