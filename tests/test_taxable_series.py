"""5-year transitional-taxable series (roll_taxable_series). Skipped if the DB / table is
not built. Proves the Final-period (period 3) selection and the gap (missing-year) handling.
"""
import warnings

import duckdb
import pytest

from screener import config
from screener.taxable_series import TABLE, taxable_series

warnings.filterwarnings("ignore")
pytestmark = pytest.mark.skipif(not config.DB_PATH.exists(), reason="screener.duckdb not built")


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(str(config.DB_PATH), read_only=True)
    yield c
    c.close()


def _has_table(con):
    return con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name=?",
                       [TABLE]).fetchone()[0] > 0


def test_series_table_loaded_one_row_per_bbl_year(con):
    if not _has_table(con):
        pytest.skip("series table not loaded")
    n = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    dist = con.execute(f"SELECT count(*) FROM (SELECT DISTINCT parcel_id, roll_year FROM {TABLE})").fetchone()[0]
    assert n == dist and n > 0      # exactly one row per (BBL, year)


def test_fy2027_count_unchanged(con):
    if not _has_table(con):
        pytest.skip("series table not loaded")
    locked = con.execute("SELECT count(*) FROM roll_class4").fetchone()[0]
    series_2027 = con.execute(f"SELECT count(*) FROM {TABLE} WHERE roll_year='2027'").fetchone()[0]
    assert locked == series_2027 == 131764     # widening did not alter the FY2027 structure


def test_230_park_uses_final_period_not_tentative(con):
    if not _has_table(con):
        pytest.skip("series table not loaded")
    s = {p["year"]: p for p in taxable_series(con, "1013000001")}
    assert set(s) == {2023, 2024, 2025, 2026, 2027}            # complete series, no gaps
    assert s[2026]["value"] == 191_000_000.0                    # FINAL, not tentative 208,192,978
    assert s[2026]["period"] == "3"
    assert [s[y]["value"] for y in (2023, 2024, 2025, 2026, 2027)] == \
        [189_967_950.0, 210_795_750.0, 210_955_500.0, 191_000_000.0, 188_421_300.0]


def test_100_broadway_full_series(con):
    if not _has_table(con):
        pytest.skip("series table not loaded")
    s = {p["year"]: p["value"] for p in taxable_series(con, "1000460003")}
    assert [s[y] for y in (2023, 2024, 2025, 2026, 2027)] == \
        [34_257_600.0, 35_712_900.0, 33_569_550.0, 35_406_555.0, 36_180_249.0]


def test_partial_parcel_missing_years_absent_not_zero(con):
    if not _has_table(con):
        pytest.skip("series table not loaded")
    s = taxable_series(con, "1006180052")          # known 4-year partial (2023 missing)
    years = {p["year"] for p in s}
    assert 2023 not in years                        # missing year is simply absent (a gap)
    assert all(p["value"] not in (0, 0.0) for p in s)   # never zero-filled
