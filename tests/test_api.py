"""API + view-model tests. Skipped if the DB isn't built. The geocode network step is
not exercised here (BBL path); live geocoding is covered in scripts/validate_geocode.py.
"""
import warnings

import pytest

from screener import config

pytestmark = pytest.mark.skipif(not config.DB_PATH.exists(), reason="screener.duckdb not built")

warnings.filterwarnings("ignore")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from screener.api import app
    return TestClient(app)


def test_home_renders_disclaimer(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "not a verdict, not tax advice, not an appraisal" in r.text


def test_dense_subject_full_view(client):
    j = client.get("/api/screen", params={"bbl": "1000090001"}).json()
    assert j["status"] == "ok"
    assert [s["key"] for s in j["signals"]] == \
        ["assessed_value_market", "tax_bill", "mv_per_gross_sf"]
    assert j["rung3"]["enabled"] is False
    assert j["provenance"]["source_dataset"] == "8y4t-faws"


def test_no_sf_subject_psf_refuses_others_render(client):
    j = client.get("/api/screen", params={"bbl": "3053480042"}).json()
    assert j["status"] == "ok"
    by_key = {s["key"]: s for s in j["signals"]}
    assert by_key["mv_per_gross_sf"]["refused"] is True
    assert by_key["assessed_value_market"]["refused"] is False
    assert by_key["tax_bill"]["refused"] is False


def test_tax_exempt_subject_refused(client):
    j = client.get("/api/screen", params={"bbl": "1000380001"}).json()
    assert j["status"] == "refused" and j["reason"] == "subject_tax_exempt"


def test_signal_carries_distribution_and_provenance(client):
    j = client.get("/api/screen", params={"bbl": "1000090001"}).json()
    sig = j["signals"][0]
    assert len(sig["distribution"]) == sig["n"]          # raw values for the chart
    assert "subject_percentile" in sig and "median" in sig


def test_rung3_off_by_default(client):
    r = client.post("/api/rung3", params={"bbl": "1000090001", "noi": "12000000"}).json()
    assert r["enabled"] is False and r["computed"] is False


def test_rung3_opt_in_computes_and_partitioned(client):
    r = client.post("/api/rung3",
                    params={"bbl": "1000090001", "noi": "12000000", "enabled": "true"}).json()
    assert r["computed"] and r["partition"] == "RUNG_3_USER_SUPPLIED"
    assert r["noi_source"] == "user_supplied" and r["stamp"] == "based on the NOI you provided"
    assert r["statement"].startswith("Your NOI of")


def test_rung3_junk_rejected(client):
    r = client.post("/api/rung3",
                    params={"bbl": "1000090001", "noi": "-5", "enabled": "true"}).json()
    assert r["rejected"] and not r["computed"]


def test_screen_html_renders_for_each_state(client):
    for bbl in ("1000090001", "3053480042", "1000380001"):
        assert client.get("/screen", params={"bbl": bbl}).status_code == 200


def test_expense_ratio_computes(client):
    r = client.post("/api/expense_ratio", params={"bbl": "1000090001", "opex": "20000000"}).json()
    assert r["computed"] and r["partition"] == "EXPENSE_RATIO_USER_SUPPLIED"
    assert r["opex_source"] == "user_supplied" and r["ratio_pct"] is not None
    assert "real estate taxes derived from 8y4t-faws@2027 (curtxbtot × 0.10848)" in r["stamp"]


def test_expense_ratio_junk_rejected(client):
    r = client.post("/api/expense_ratio", params={"bbl": "1000090001", "opex": "-5"}).json()
    assert r["rejected"] and not r["computed"]


def test_expense_ratio_tax_exempt_refused(client):
    r = client.post("/api/expense_ratio", params={"bbl": "1000380001", "opex": "20000000"}).json()
    assert r["rejected"] and r["rejection_reason"] == "subject_tax_exempt"


def test_re_taxes_matches_tax_bill_subject_value(client):
    """Subject RE-taxes line == the Tax Bill chart's subject value (same derived figure)."""
    j = client.get("/api/screen", params={"bbl": "1012770027"}).json()
    re_taxes = j["subject"]["real_estate_taxes"]
    tax_sig = next(s for s in j["signals"] if s["key"] == "tax_bill")
    assert abs(re_taxes - tax_sig["subject_value"]) < 1.0
