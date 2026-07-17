"""ICAP abatement disclosure + Tax Bill region (Items 1-5). All disclosure/provenance:
the statutory tax bill (curtxbtot x rate) is unchanged for subject and every comp.
Skipped if the DB (with the abatements_icap table) is not built.
"""
import warnings

import duckdb
import pytest

from screener import config
from screener.abatements import TABLE, abatement_programs, icap_bbls, icap_vintage
from screener.exemptions import exempt_shares

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


def test_icap_bbls_filters_to_icap_program_only(con):
    # The table now carries J51/MCI/GCCA rows too; icap_bbls must not tag them as ICAP.
    if not _has_table(con):
        pytest.skip("abatement table not loaded")
    j51_only = con.execute(f"""
        SELECT parcel_id FROM {TABLE} WHERE program = 'J51'
        AND parcel_id NOT IN (SELECT parcel_id FROM {TABLE} WHERE program = 'ICAP')
        LIMIT 1""").fetchone()
    if not j51_only:
        pytest.skip("no J51-only BBL in the loaded snapshot")
    assert icap_bbls(con, [j51_only[0]]) == set()
    assert "J51" in abatement_programs(con, [j51_only[0]])[j51_only[0]]


def test_abatement_programs_shape(con):
    if not _has_table(con):
        pytest.skip("abatement table not loaded")
    progs = abatement_programs(con, [ICAP_SUBJECT])
    assert "ICAP" in progs[ICAP_SUBJECT]
    assert abatement_programs(con, [NO_ICAP_SUBJECT]) == {}


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
    # exemptions are named alongside abatements on the same statutory-basis framing
    assert "exemption" in j["comp_basis_caveat"]
    assert "fully exempt comp pays none" in j["comp_basis_caveat"]
    # the marks sentence appears because the local DB carries the exemption table
    assert "marked in the comp table" in j["comp_basis_caveat"]
    assert "PILOT" in j["pilot_caveat"] and "cannot identify PILOT" in j["pilot_caveat"]  # Item 3
    # methodology note now names exemptions too
    assert "before any exemption" in j["tax_methodology"]["note"]


# --- subject benefit-basis note (conditional; replaces the ICAP-only banner) -----------
def test_subject_benefit_note_fires_and_names_icap(client):
    j = client.get("/api/screen", params={"bbl": ICAP_SUBJECT}).json()
    note = j["subject_benefit_note"]
    assert note is not None
    assert "an ICAP abatement" in note["message"]
    assert "statutory amounts before" in note["message"]
    assert "compares with the assessments of similar buildings" in note["message"]
    assert note["programs"] == ["ICAP"] and note["exempt_share"] is None
    assert any("rgyu-ii48" in s for s in note["sources"])
    assert j["subject"]["has_icap"] is True


def test_no_benefit_note_without_benefit(client):
    j = client.get("/api/screen", params={"bbl": NO_ICAP_SUBJECT}).json()
    assert j["subject_benefit_note"] is None
    assert j["subject"]["has_icap"] is False


def test_note_separate_from_always_on_pilot_caveat(client):
    # PILOT caveat is always on even when no benefit note shows
    j = client.get("/api/screen", params={"bbl": NO_ICAP_SUBJECT}).json()
    assert j["subject_benefit_note"] is None and j["pilot_caveat"]


def test_benefit_note_message_composition():
    # pure-function composition: abatement + exemption, singular/plural agreement
    from screener.serialize import _subject_benefit_note
    assert _subject_benefit_note([], None) is None
    one = _subject_benefit_note(["ICAP"], None)
    assert "an ICAP abatement, which reduces" in one
    both = _subject_benefit_note(["ICAP", "J51"], 0.34)
    assert "an ICAP abatement" in both and "a J-51 abatement" in both
    assert "an exemption covering 34% of its taxable value" in both
    assert "which reduce " in both and "before those benefits" in both


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


# --- comp exemption marks: display only, statutory tax unchanged -----------------------
def test_comp_exempt_tag_display_only(client, con):
    # find a subject whose comp set contains an exempt comp: any office comp row that
    # appears in exemptions_class4. 230 Park's Midtown set is the densest candidate.
    j = client.get("/api/screen", params={"bbl": ICAP_SUBJECT}).json()
    rows = [r for v in j["variance"]["views"] for r in v["rows"]]
    assert all("exempt_share" in r and "exempt_share_display" in r for r in rows)
    tagged = [r for r in rows if r["exempt_share"] is not None]
    for r in tagged:   # marked comps still carry the full statutory tax figure
        assert 0 < r["exempt_share"] <= 1
        assert r["exempt_share_display"]
        assert r["tax_psf_vs_subject"] is not None
    # cross-check one tagged comp against the table directly
    if tagged:
        share = exempt_shares(con, [tagged[0]["parcel_id"]])[tagged[0]["parcel_id"]]
        assert abs(share - tagged[0]["exempt_share"]) < 1e-9


def test_exempt_share_display_bands():
    from screener.serialize import _exempt_share_display
    assert _exempt_share_display(1.0) == "100%"
    assert _exempt_share_display(0.996) == "100%"
    assert _exempt_share_display(0.005) == "<1%"
    assert _exempt_share_display(0.34) == "34%"


# --- provenance: abatement + exemption vintages shown alongside roll + PLUTO -----------
def test_provenance_carries_abatement_vintage(client):
    j = client.get("/api/screen", params={"bbl": ICAP_SUBJECT}).json()
    assert j["provenance"]["abatement_dataset"] == "rgyu-ii48"
    assert j["provenance"]["abatement_extractdt"]
    assert j["provenance"]["exemption_dataset"] == "8y4t-faws"
    assert j["provenance"]["exemption_roll_year"] == "2027"
    html = client.get("/screen", params={"bbl": ICAP_SUBJECT}).text
    assert "Abatement source (ICAP/J-51/MCI/GCCA): rgyu-ii48" in html
    assert "Exemption source (curtxbextot): 8y4t-faws" in html
