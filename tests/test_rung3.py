"""RUNG 3 correctness + the fencing discipline (off by default, stamped, partitioned,
junk-rejected, exempt-refused). Pure-function tests need no DB.
"""
from datetime import date

import pytest

from screener.rung3 import PARTITION, STAMP, compute_rung3
from screener.schema import Citation


def _cite():
    return Citation(source_dataset="8y4t-faws", dataset_version="roll-v", roll_year="2027",
                    retrieval_date=date(2026, 6, 19), parcel_id="1000000001")


def test_off_by_default():
    r = compute_rung3(10_000_000, _cite(), 700_000, "1000000001")  # enabled defaults False
    assert not r.enabled and not r.computed and r.implied_cap_rate is None
    assert "off by default" in r.message.lower()


def test_normal_noi_computes_correct_cap_rate():
    r = compute_rung3(10_000_000, _cite(), 700_000, "1000000001", enabled=True)
    assert r.computed and not r.rejected
    assert r.implied_cap_rate == 0.07 and r.implied_cap_rate_pct == 7.0   # 700k / 10M
    assert r.user_noi == 700_000 and r.noi_source == "user_supplied"
    assert r.market_value == 10_000_000


def test_output_is_stamped_and_possessive():
    r = compute_rung3(10_000_000, _cite(), 700_000, "1000000001", enabled=True)
    assert STAMP in r.statement
    assert r.statement.lower().startswith("your noi")          # possessive framing
    assert "the cap rate is" not in r.statement.lower()         # never authoritative phrasing


def test_market_value_cited_noi_uncited():
    r = compute_rung3(10_000_000, _cite(), 700_000, "1000000001", enabled=True)
    assert r.market_value_citation is not None
    assert r.market_value_citation["source_dataset"] == "8y4t-faws"
    # the NOI carries no citation object anywhere on the result
    assert "noi_citation" not in r.__dict__ and r.noi_source == "user_supplied"


@pytest.mark.parametrize("bad,reason", [
    (0, "noi_not_positive"),
    (-5000, "noi_not_positive"),
    (0.0, "noi_not_positive"),
    ("abc", "noi_non_numeric"),
    ("", "noi_non_numeric"),
    (None, "noi_non_numeric"),
    (True, "noi_non_numeric"),
    (float("nan"), "noi_non_numeric"),
    (float("inf"), "noi_non_numeric"),
])
def test_junk_noi_rejected_no_computation(bad, reason):
    r = compute_rung3(10_000_000, _cite(), bad, "1000000001", enabled=True)
    assert r.rejected and r.rejection_reason == reason
    assert not r.computed and r.implied_cap_rate is None


def test_numeric_string_noi_accepted():
    r = compute_rung3(10_000_000, _cite(), "700000", "1000000001", enabled=True)
    assert r.computed and r.implied_cap_rate_pct == 7.0


@pytest.mark.parametrize("mv", [0, -1, None, 0.0])
def test_tax_exempt_subject_cannot_run(mv):
    r = compute_rung3(mv, _cite(), 700_000, "1000000001", enabled=True)
    assert r.rejected and r.rejection_reason == "subject_tax_exempt"
    assert not r.computed and r.implied_cap_rate is None        # never divides


def test_partition_marker_present():
    r = compute_rung3(10_000_000, _cite(), 700_000, "1000000001", enabled=True)
    assert r.partition == PARTITION == "RUNG_3_USER_SUPPLIED"


def test_result_type_is_not_a_public_signal():
    # Structural partition: the RUNG 3 object is a distinct type with none of the
    # public-signal field names, so it cannot be blended into a distribution.
    r = compute_rung3(10_000_000, _cite(), 700_000, "1000000001", enabled=True)
    for public_field in ("mean", "median", "subject_percentile", "differs_on", "signals"):
        assert not hasattr(r, public_field)
