"""Loader invariants. Skipped automatically if the DuckDB hasn't been built yet
(these assert against real loaded data, not fixtures).

Build with:  PYTHONPATH=src python -m screener.loader
"""
import duckdb
import pytest

from screener import config

pytestmark = pytest.mark.skipif(
    not config.DB_PATH.exists(), reason="screener.duckdb not built; run the loader first"
)


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(str(config.DB_PATH), read_only=True)
    yield c
    c.close()


def _has_table(con, name):
    return con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]
    ).fetchone()[0] == 1


def test_canonical_table_is_one_row_per_bbl(con):
    if not _has_table(con, "roll_class4"):
        pytest.skip("roll_class4 not present")
    rows, bbls = con.execute(
        "SELECT count(*), count(DISTINCT parcel_id) FROM roll_class4"
    ).fetchone()
    assert rows == bbls, "canonical roll must be one row per BBL"


def test_provenance_never_null(con):
    if not _has_table(con, "roll_class4"):
        pytest.skip("roll_class4 not present")
    nulls = con.execute(
        """
        SELECT count(*) FROM roll_class4
        WHERE parcel_id IS NULL OR source_dataset IS NULL OR dataset_version IS NULL
           OR roll_year IS NULL OR retrieval_date IS NULL
        """
    ).fetchone()[0]
    assert nulls == 0


def test_scope_is_class4_only(con):
    if not _has_table(con, "roll_class4"):
        pytest.skip("roll_class4 not present")
    classes = [r[0] for r in con.execute("SELECT DISTINCT tax_class FROM roll_class4").fetchall()]
    assert classes == ["4"]


def test_market_value_populated(con):
    if not _has_table(con, "roll_class4"):
        pytest.skip("roll_class4 not present")
    total, nn = con.execute(
        "SELECT count(*), count(curmkttot) FROM roll_class4"
    ).fetchone()
    assert nn / total > 0.99, "market value should be near-fully populated"
