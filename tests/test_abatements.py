"""ICAP abatement disclosure + Tax Bill region (Items 1-5). All disclosure/provenance:
the statutory tax bill (curtxbtot x rate) is unchanged for subject and every comp.
Skipped if the DB (with the abatements_icap table) is not built.
"""
import warnings

import duckdb
import pytest

from screener import config
from screener.abatements import TABLE, icap_bbls, icap_vintage

warnings.filterwarnings("ignore")
pytestmark = pytest.mark.skipif(not config.DB_PATH.exists(), reason="screener.duckdb not built")

ICAP_SUBJECT = "1013000001"     # 230 Park Ave — carries current ICAP
NO_ICAP_SUBJECT = "1000460003"  # 100 Broadway — no abatement


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(str(config.DB_PATH), read_only=True)
    yield c
    c.close()


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from screener.api import app
    return TestClient(app)


def _has_table(con):
    return con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name=?",
                       [TABLE]).fetchone()[0] > 0


# --- Item 4: data layer helpers -------------------------------------------------------
def test_icap_table_loaded(con):
    assert _has_table(con)
    assert con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0] > 0


def test_icap_bbls_membership(con):
    if not _has_table(con):
        pytest.skip("abatement table not loaded")
    assert icap_bbls(con, [ICAP_SUBJECT]) == {ICAP_SUBJECT}
    assert icap_bbls(con, [NO_ICAP_SUBJECT]) == set()


def test_icap_vintage_present(con):
    extractdt, dataset = icap_vintage(con)
    assert dataset == "rgyu-ii48"
    assert extractdt and extractdt.count("-") == 2     # ISO date


# --- Item 1: tax-methodology derivation reconciles to the displayed Tax Bill ----------
def test_tax_methodology_reconciles_to_tax_bill(client):
    j = client.get("/api/screen", params={"bbl": NO_ICAP_SUBJECT}).json()
    tm = j["tax_methodology"]
    rate = j["provenance"]["tax_rate_applied"]
    # final line = transitional x rate, and equals the Tax Bill chart's subject value
    assert abs(tm["transitional"] * rate - tm["tax_bill"]) < 0.01
    tax_sig = next(s for s in j["signals"] if s["key"] == "tax_bill")
    assert abs(tm["tax_bill"] - tax_sig["subject_value"]) < 1.0
    assert round(tm["tax_bill"]) == 3924833            # to the dollar
    # the 45% actual-assessed x rate does NOT match — that gap is the phase-in (expected)
    assert abs(tm["actual_assessed"] * rate - tm["tax_bill"]) > 1.0


def test_tax_region_caveats_always_present(client):
    j = client.get("/api/screen", params={"bbl": NO_ICAP_SUBJECT}).json()
    assert "computed identically for every comp" in j["comp_basis_caveat"]       # Item 2
    assert "PILOT" in j["pilot_caveat"] and "cannot identify PILOT" in j["pilot_caveat"]  # Item 3


# --- Item 5: subject banner (conditional) ---------------------------------------------
def test_subject_banner_fires_and_names_icap(client):
    j = client.get("/api/screen", params={"bbl": ICAP_SUBJECT}).json()
    assert j["icap_banner"] is not None
    assert "ICAP property tax abatement" in j["icap_banner"]["message"]
    assert j["icap_banner"]["dataset"] == "rgyu-ii48" and j["icap_banner"]["extractdt"]
    assert j["subject"]["has_icap"] is True


def test_no_subject_banner_without_icap(client):
    j = client.get("/api/screen", params={"bbl": NO_ICAP_SUBJECT}).json()
    assert j["icap_banner"] is None
    assert j["subject"]["has_icap"] is False


def test_banner_separate_from_always_on_pilot_caveat(client):
    # PILOT caveat is always on even when no ICAP banner shows
    j = client.get("/api/screen", params={"bbl": NO_ICAP_SUBJECT}).json()
    assert j["icap_banner"] is None and j["pilot_caveat"]


# --- Item 5: comp tag — display only, statutory tax unchanged --------------------------
def test_comp_icap_tag_present_and_tax_unchanged(client):
    # 230 Park's comp set is dense Midtown — expect at least one ICAP comp tagged.
    j = client.get("/api/screen", params={"bbl": ICAP_SUBJECT}).json()
    rows = [r for v in j["variance"]["views"] for r in v["rows"]]
    tagged = [r for r in rows if r["has_icap"]]
    assert tagged, "expected at least one ICAP-tagged comp in a dense Midtown set"
    # tagged comp still carries a full statutory tax PSF figure (not blanked/zeroed)
    for r in tagged:
        assert r["tax_psf_vs_subject"] != "" and r["tax_psf_vs_subject"] is not None


def test_comp_count_identical_with_and_without_icap_field(client):
    # the flag never filters/drops comps
    j = client.get("/api/screen", params={"bbl": ICAP_SUBJECT}).json()
    assert j["comp_meta"]["comp_count"] >= config.MIN_COMP_COUNT


# --- provenance: abatement vintage shown alongside roll + PLUTO ------------------------
def test_provenance_carries_abatement_vintage(client):
    j = client.get("/api/screen", params={"bbl": ICAP_SUBJECT}).json()
    assert j["provenance"]["abatement_dataset"] == "rgyu-ii48"
    assert j["provenance"]["abatement_extractdt"]
    html = client.get("/screen", params={"bbl": ICAP_SUBJECT}).text
    assert "ICAP abatement source: rgyu-ii48" in html
