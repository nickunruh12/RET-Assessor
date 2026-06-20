"""PLUTO join invariants. Skipped if the DuckDB / join tables aren't built yet.

Build with:
    PYTHONPATH=src python -m screener.loader
    PYTHONPATH=src python -m screener.pluto
"""
import duckdb
import pytest

from screener import config

pytestmark = pytest.mark.skipif(
    not config.DB_PATH.exists(), reason="screener.duckdb not built; run loader + pluto first"
)


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(str(config.DB_PATH), read_only=True)
    yield c
    c.close()


def _has(con, name):
    return con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]
    ).fetchone()[0] == 1


def _require(con, name):
    if not _has(con, name):
        pytest.skip(f"{name} not present")


def test_parcels_is_one_row_per_bbl(con):
    _require(con, "parcels")
    rows, bbls = con.execute("SELECT count(*), count(DISTINCT parcel_id) FROM parcels").fetchone()
    assert rows == bbls


def test_every_pluto_miss_is_excluded_with_reason(con):
    _require(con, "parcels")
    _require(con, "exclusions")
    # Every parcel without a usable PLUTO BldgArea must be routed to exclusions
    # (spec: every PLUTO non-match logged with a reason code), regardless of
    # whether the roll fallback later rescues it.
    unrouted = con.execute(
        """
        SELECT count(*) FROM parcels p
        WHERE (p.pluto_bldgarea IS NULL OR p.pluto_bldgarea <= 0)
          AND p.parcel_id NOT IN (SELECT parcel_id FROM exclusions)
        """
    ).fetchone()[0]
    assert unrouted == 0
    blank_reason = con.execute(
        "SELECT count(*) FROM exclusions WHERE reason_code IS NULL"
    ).fetchone()[0]
    assert blank_reason == 0


def test_matched_parcels_carry_pluto_provenance(con):
    _require(con, "parcels")
    bad = con.execute(
        """
        SELECT count(*) FROM parcels
        WHERE pluto_bldgclass IS NOT NULL
          AND (pluto_source_dataset IS NULL OR pluto_dataset_version IS NULL
               OR pluto_retrieval_date IS NULL)
        """
    ).fetchone()[0]
    assert bad == 0


def test_sf_source_is_labeled_when_sf_present(con):
    _require(con, "parcels")
    bad = con.execute(
        "SELECT count(*) FROM parcels WHERE sf IS NOT NULL AND sf_source IS NULL"
    ).fetchone()[0]
    assert bad == 0


def test_parcels_no_sf_is_persisted_and_consistent(con):
    _require(con, "parcels_no_sf")
    # Must be a real table that exactly equals the no-gross-building-area set.
    table_n = con.execute("SELECT count(*) FROM parcels_no_sf").fetchone()[0]
    query_n = con.execute("SELECT count(*) FROM parcels WHERE sf IS NULL").fetchone()[0]
    assert table_n == query_n
    # Every no-SF parcel still carries provenance (it appears in distributions).
    bad = con.execute(
        "SELECT count(*) FROM parcels_no_sf WHERE source_dataset IS NULL OR parcel_id IS NULL"
    ).fetchone()[0]
    assert bad == 0


def test_commercial_office_retail_match_is_near_total(con):
    _require(con, "parcels")
    total, matched = con.execute(
        """
        SELECT count(*), count(*) FILTER (WHERE pluto_bldgclass IS NOT NULL)
        FROM parcels WHERE bldg_class LIKE 'O%' OR bldg_class LIKE 'K%'
        """
    ).fetchone()
    assert matched / total > 0.99  # Phase 2 expected ~99.98% on O*/K*
