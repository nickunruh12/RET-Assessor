"""Custom-comps backend (manual-override lane). Verifies per-comp validation, origin tagging,
hybrid auto-fill, land-dominant handling, and the always-present not-vetted flag — without
touching the auto-selection engine. Comp BBLs are derived from the live auto-screen so the tests
track the loaded DB.
"""
import warnings

import pytest

from screener import config

warnings.filterwarnings("ignore")
pytestmark = pytest.mark.skipif(not config.DB_PATH.exists(), reason="screener.duckdb not built")

SUBJECT = "1013010001"          # office
NON_CLASS4 = "5000200001"       # exists in PLUTO, not in the class-4 roll
LAND_DOMINANT = "4047150009"    # PLUTO coverage < 0.30
RETAIL_COMP = "1000200012"      # K4 — cross-type for an office subject


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from screener.api import app
    return TestClient(app)


@pytest.fixture(scope="module")
def office_comps(client):
    # 8 real office comps for the subject, taken from its auto comp set.
    j = client.get("/api/screen", params={"bbl": SUBJECT}).json()
    return [p["bbl"] for p in j["signals"][0]["comp_points"]][:8]


def _screen(client, comps, fill="none"):
    return client.post("/api/v1/custom_screen",
                       json={"subject_bbl": SUBJECT, "comp_bbls": comps, "fill": fill}).json()


def test_not_vetted_flag_on_every_response(client, office_comps):
    ok = _screen(client, office_comps[:5])
    refused = _screen(client, office_comps[:1])          # 1 valid -> refuse
    assert ok["user_comps_not_vetted"] is True and ok["status"] == "ok"
    assert refused["user_comps_not_vetted"] is True and refused["status"] == "refused"
    assert ok["selection_safeguards_applied"] is False
    assert ok["comp_source"]["selection_safeguards_applied"] is False


def test_thin_set_exposes_both_options(client, office_comps):
    r = _screen(client, office_comps[:5])
    assert r["thin_set"] is True
    opt = r["options"]
    assert opt["below_min"] is True and opt["min_comp_count"] == 8
    assert opt["choices"]["thin_run"]["available"] is True
    assert opt["choices"]["autofill"]["available"] is True        # office has an auto engine
    assert "less reliable" in opt["reliability_note"].lower()


def test_autofill_reaches_min_and_tags_origin(client, office_comps):
    r = _screen(client, office_comps[:5], fill="autofill")
    cs = r["comp_source"]
    assert cs["screened_count"] == 8
    assert cs["user_supplied_count"] == 5 and cs["tool_selected_count"] == 3
    origins = [c["origin"] for c in r["comps"]]
    assert origins.count("user-supplied") == 5 and origins.count("tool-selected") == 3
    assert "5 user-supplied" in cs["comp_mix"] and "3 tool-selected" in cs["comp_mix"]


def test_every_comp_carries_origin(client, office_comps):
    r = _screen(client, office_comps[:5], fill="autofill")
    assert all(c["origin"] in ("user-supplied", "tool-selected") for c in r["comps"])
    # origin is also injected onto the comps the response exposes in the variance table
    rows = [row for v in r["variance"]["views"] for row in v["rows"]]
    assert rows and all("origin" in row for row in rows)


def test_excludes_non_class4_comp_with_reason(client, office_comps):
    r = _screen(client, office_comps[:4] + [NON_CLASS4])
    assert r["status"] == "ok"
    assert r["comp_source"]["valid_count"] == 4                   # exclusion reflected in the count
    excluded = {e["bbl"]: e["reason"] for e in r["comp_source"]["excluded"]}
    assert NON_CLASS4 in excluded and "not tax class 4" in excluded[NON_CLASS4]


def test_cross_type_comp_screened_and_tagged(client, office_comps):
    r = _screen(client, office_comps[:4] + [RETAIL_COMP])
    tag = next(c for c in r["comps"] if c["bbl"] == RETAIL_COMP)
    assert r["status"] == "ok"
    assert tag["asset_type"] == "retail" and tag["cross_type"] is True


def test_land_dominant_excluded_from_per_sf_kept_in_value(client, office_comps):
    r = _screen(client, office_comps[:8] + [LAND_DOMINANT])       # 8 clean + 1 land-dominant
    comp = next(c for c in r["comps"] if c["bbl"] == LAND_DOMINANT)
    assert comp["land_dominant"] is True
    val = next(s for s in r["signals"] if s["key"] == "assessed_value_market")
    psf = next(s for s in r["signals"] if s["key"] == "mv_per_gross_sf")
    assert val["n"] == 9                                          # kept in the value distribution
    assert psf["land_dominant_excluded"] == 1                     # excluded from per-SF
    assert psf["n"] == 8


def test_refuses_below_two_valid_comps(client, office_comps):
    r = _screen(client, [office_comps[0]])                        # 1 valid
    assert r["status"] == "refused" and r["reason"] == "insufficient_valid_comps"
    # even on refusal the validation report is present so the UI can explain
    assert r["comp_source"]["valid_count"] == 1


# --- Custom-comps UI flow (wizard routing + shared components) -------------------------------
def test_wizard_resolves_subject_via_shared_partial(client):
    r = client.get("/custom", params={"bbl": SUBJECT}).text
    assert "Confirm this is the right parcel" in r
    # the shared subject-facts partial rendered (same fields as the auto path)
    assert "Estimated Market Value According to DOF" in r and "<dt>BBL</dt>" in r
    assert 'id="comp-entry"' in r and 'data-autofill-available="true"' in r   # office -> autofill ok


def test_wizard_refuses_non_class4_subject(client):
    r = client.get("/custom", params={"bbl": NON_CLASS4}).text
    assert "not tax class 4" in r and 'id="comp-entry"' not in r


def test_validate_comp_endpoint(client):
    def v(bbl):
        return client.post("/api/v1/custom_validate_comp",
                           json={"subject_bbl": SUBJECT, "comp_bbls": [bbl]}).json()
    assert v(NON_CLASS4)["status"] == "excluded" and "not tax class 4" in v(NON_CLASS4)["reason"]
    xt = v(RETAIL_COMP)
    assert xt["status"] == "valid" and xt["cross_type"] is True


def test_custom_result_renders_full_output_plus_layers(client, office_comps):
    comps = ",".join(office_comps[:5])
    out = client.get("/custom_result",
                     params={"subject": SUBJECT, "comps": comps, "fill": "autofill"}).text
    # full auto output reused
    assert 'class="comp-table"' in out and 'id="chart-assessed_value_market"' in out
    # custom layers added
    assert "not screened by the tool's selection logic" in out          # not-vetted stamp
    assert "<th>Origin</th>" in out                                      # origin column
    assert "tool-selected to reach the 8-comp minimum" in out           # mix disclosure
