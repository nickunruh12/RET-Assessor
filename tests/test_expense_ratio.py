"""Expense Ratio Check: compute, guardrails, and the dynamic benchmark note (render
when a (metro, product_type) range exists, NOT when it doesn't)."""
import pytest

from screener.expense_ratio import compute_expense_ratio
from screener.jurisdiction import CompCriteria, get_jurisdiction
from screener.serialize import _expense_section

STAMP_ROLL = "8y4t-faws@2027"
RATE = 0.10848


# --- compute ---------------------------------------------------------------
def test_normal_ratio_computes():
    r = compute_expense_ratio(100_000, 250_000, STAMP_ROLL, RATE, "1")
    assert r.computed and not r.rejected
    assert r.ratio_pct == 40.0
    assert r.statement == ("Your real estate taxes of $100,000 are 40.00% of the operating "
                           "expense you provided ($250,000).")
    assert r.real_estate_taxes == 100_000 and r.user_opex == 250_000


def test_stamp_present_and_correct():
    r = compute_expense_ratio(100_000, 250_000, STAMP_ROLL, RATE, "1")
    assert r.stamp == (f"operating expense: user-supplied (no citation) · real estate taxes "
                       f"derived from {STAMP_ROLL} (curtxbtot × {RATE})")
    assert r.opex_source == "user_supplied"


def test_numeric_string_opex_accepted():
    r = compute_expense_ratio(100_000, "200000", STAMP_ROLL, RATE, "1")
    assert r.computed and r.ratio_pct == 50.0


# --- guardrails ------------------------------------------------------------
@pytest.mark.parametrize("bad,reason", [
    (0, "opex_not_positive"), (-100, "opex_not_positive"), (0.0, "opex_not_positive"),
    ("abc", "opex_non_numeric"), ("", "opex_non_numeric"), (None, "opex_non_numeric"),
    (True, "opex_non_numeric"), (float("nan"), "opex_non_numeric"), (float("inf"), "opex_non_numeric"),
])
def test_junk_opex_rejected(bad, reason):
    r = compute_expense_ratio(100_000, bad, STAMP_ROLL, RATE, "1")
    assert r.rejected and r.rejection_reason == reason and not r.computed


@pytest.mark.parametrize("taxes", [0, -1, None, 0.0])
def test_tax_exempt_subject_cannot_run(taxes):
    r = compute_expense_ratio(taxes, 250_000, STAMP_ROLL, RATE, "1")
    assert r.rejected and r.rejection_reason == "subject_tax_exempt" and not r.computed


# --- dynamic benchmark note ------------------------------------------------
@pytest.fixture
def setup():
    crit = CompCriteria.load()
    return get_jurisdiction(crit.jurisdiction), crit


def test_note_renders_for_nyc_office(setup):
    juris, crit = setup
    sec = _expense_section(juris, crit, {"bldg_class": "O1"})
    assert sec["product_type"] == "office" and sec["metro"] == "New York City"
    assert sec["benchmark_note"] == (
        "40–50% = typical range for the real estate tax share of operating expenses for an "
        "office building in New York City (general rule of thumb, not a sourced benchmark).")


def test_retail_note_mirrors_office_with_retail_range(setup):
    juris, crit = setup
    # Retail (K*) now has a configured 35–45% range that mirrors office exactly (only the
    # range and the word "retail" differ; same "not a sourced benchmark" label, no verdict).
    sec = _expense_section(juris, crit, {"bldg_class": "K1"})
    assert sec["product_type"] == "retail"
    assert sec["benchmark_note"] == (
        "35–45% = typical range for the real estate tax share of operating expenses for a "
        "retail building in New York City (general rule of thumb, not a sourced benchmark).")


def test_note_absent_for_unconfigured_product_type(setup):
    juris, crit = setup
    # Industrial (F*) maps to a product type, but no (New York City, industrial) range exists.
    sec = _expense_section(juris, crit, {"bldg_class": "F1"})
    assert sec["product_type"] == "industrial"
    assert sec["benchmark_note"] is None        # no range -> no note (never invented)


def test_note_absent_for_unmapped_class(setup):
    juris, crit = setup
    sec = _expense_section(juris, crit, {"bldg_class": "Z9"})
    assert sec["product_type"] is None and sec["benchmark_note"] is None


def test_benchmark_note_has_no_verdict_language(setup):
    juris, crit = setup
    note = _expense_section(juris, crit, {"bldg_class": "O1"})["benchmark_note"].lower()
    for banned in ("high", "low", "over", "under", "outlier", "should", "too "):
        assert banned not in note
