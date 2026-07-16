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
    assert '<th class="origin-col">Origin</th>' in out                   # origin column
    assert "tool-selected to reach the 8-comp minimum" in out           # mix disclosure


# --- Out-of-scope subject (custom-mode escape hatch, disclosed) ------------------------------
HOTEL = "1008680036"           # HB hotel — class 4, but not O/K/F (outside auto-screen scope)


def test_out_of_scope_subject_flag_notice_and_enforcement(client, office_comps):
    # API carries the flag + notice; auto-fill is enforced OFF; thin-run still works.
    r = client.post("/api/v1/custom_screen",
                    json={"subject_bbl": HOTEL, "comp_bbls": office_comps[:5], "fill": "autofill"}).json()
    assert r["status"] == "ok"
    assert r["subject_out_of_scope_for_auto"] is True
    assert r["scope_notice"] and "screens automatically" in r["scope_notice"]
    assert r["comp_source"]["tool_selected_count"] == 0                # autofill ignored/enforced off
    assert r["options"]["choices"]["autofill"]["available"] is False
    assert r["options"]["choices"]["thin_run"]["available"] is True


def test_in_scope_subject_has_no_scope_notice(client, office_comps):
    r = client.post("/api/v1/custom_screen",
                    json={"subject_bbl": SUBJECT, "comp_bbls": office_comps[:5], "fill": "none"}).json()
    assert r["subject_out_of_scope_for_auto"] is False and r["scope_notice"] is None
    assert r["options"]["choices"]["autofill"]["available"] is True    # both options still offered


def test_wizard_shows_scope_notice_for_out_of_scope_subject(client):
    r = client.get("/custom", params={"bbl": HOTEL}).text
    assert 'class="scope-notice"' in r and "outside the asset types this version" in r
    assert 'data-autofill-available="false"' in r and 'id="comp-entry"' in r   # can still proceed


# --- Size-dissimilar MARKING (no suppression), per subject-type band ------------------------
def _sf(bbl):
    import duckdb
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    try:
        return con.execute("SELECT sf FROM parcels WHERE parcel_id=?", [bbl]).fetchone()[0]
    finally:
        con.close()


def _dissimilar_bbl(subject, mult):
    import duckdb
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    try:
        tgt = _sf(subject) * mult
        row = con.execute(
            "SELECT parcel_id FROM parcels WHERE curmkttot>0 AND sf BETWEEN ? AND ? AND parcel_id<>? "
            "ORDER BY abs(sf-?) LIMIT 1", [tgt * 0.9, tgt * 1.1, subject, tgt]).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def _psf(r):
    return next(s for s in r["signals"] if s["key"] == "mv_per_gross_sf")


def test_size_dissimilar_marked_not_suppressed(client, office_comps):
    big = _dissimilar_bbl(SUBJECT, 2.5)
    r = _screen(client, office_comps[:5] + [big])
    row = next(row for v in r["variance"]["views"] for row in v["rows"] if row["parcel_id"] == big)
    p = _psf(r)
    assert row["size_dissimilar"] is True and r["per_sf_size_flag"] is True      # marked
    assert "±50%" in p["size_flag_note"] and "no size restriction" in p["size_flag_note"]
    assert p["subject_percentile"] is not None and p["percentile_n"] is None      # NOT suppressed


def test_clean_set_has_no_marks_or_note(client, office_comps):
    r = _screen(client, office_comps[:5])           # auto comps are size-similar
    assert not any(row.get("size_dissimilar") for v in r["variance"]["views"] for row in v["rows"])
    assert r.get("per_sf_size_flag") is False and _psf(r).get("size_flag_note") is None


def test_band_is_50_for_office_75_for_industrial(client):
    off = _dissimilar_bbl(SUBJECT, 2.5)
    ro = _screen(client, [c for c in _auto_comps(client, SUBJECT)[:4]] + [off])
    assert "±50%" in _psf(ro)["size_flag_note"]
    IND = "3000320029"
    indf = _dissimilar_bbl(IND, 3.0)
    ri = _screen_for(client, IND, [c for c in _auto_comps(client, IND)[:4]] + [indf])
    assert "±75%" in _psf(ri)["size_flag_note"]


def test_out_of_scope_marks_at_50_and_notice_names_borrowed_band(client, office_comps):
    HOTEL = "1008680036"
    r = _screen_for(client, HOTEL, office_comps[:5] + [_dissimilar_bbl(HOTEL, 2.5)])
    assert "±50%" in _psf(r)["size_flag_note"]
    assert "size-dissimilar marking uses a ±50%" in r["scope_notice"]


def _auto_comps(client, bbl):
    j = client.get("/api/screen", params={"bbl": bbl}).json()
    return [p["bbl"] for p in j["signals"][0]["comp_points"]]


def _screen_for(client, subject, comps, fill="none"):
    return client.post("/api/v1/custom_screen",
                       json={"subject_bbl": subject, "comp_bbls": comps, "fill": fill}).json()


# --- Comp entry improvements: bbl field, size-dissimilar on entry, condo branches -------------
def _validate(client, **payload):
    return client.post("/api/v1/custom_validate_comp",
                       json={"subject_bbl": SUBJECT, **payload}).json()


def test_validate_accepts_bbl_field_and_back_compat(client, office_comps):
    a = _validate(client, bbl=office_comps[0])
    b = _validate(client, comp_bbls=[office_comps[0]])      # legacy shape still honored
    assert a["status"] == "valid" and a == b


def test_validate_returns_entry_time_facts(client, office_comps):
    v = _validate(client, bbl=office_comps[0])
    for k in ("address", "bldg_class", "sf", "year_built", "distance_miles",
              "size_dissimilar", "size_band_pct"):
        assert k in v


def test_size_dissimilar_on_entry_uses_subject_type_band(client):
    import duckdb
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    try:
        def comp_near(subject, mult):
            sf = con.execute("SELECT sf FROM parcels WHERE parcel_id=?", [subject]).fetchone()[0]
            return con.execute(
                "SELECT parcel_id FROM parcels WHERE curmkttot>0 AND bldg_class NOT LIKE 'R%' "
                "AND TRY_CAST(substr(parcel_id,7,4) AS INT)<1001 AND sf BETWEEN ? AND ? LIMIT 1",
                [sf * (mult - .05), sf * (mult + .05)]).fetchone()[0]
        # office: 2.5x -> dissimilar at ±50%
        v = _validate(client, bbl=comp_near(SUBJECT, 2.5))
        assert v["size_dissimilar"] is True and v["size_band_pct"] == "50"
        # industrial: 1.65x is INSIDE ±75%; 2.5x is outside
        IND = "3000320029"
        vm = client.post("/api/v1/custom_validate_comp",
                         json={"subject_bbl": IND, "bbl": comp_near(IND, 1.65)}).json()
        vb = client.post("/api/v1/custom_validate_comp",
                         json={"subject_bbl": IND, "bbl": comp_near(IND, 2.5)}).json()
        assert vm["size_dissimilar"] is False and vm["size_band_pct"] == "75"
        assert vb["size_dissimilar"] is True and vb["size_band_pct"] == "75"
    finally:
        con.close()


def test_condo_billing_lot_gets_specific_message(client):
    v = _validate(client, bbl="1013027501")                  # 277 Park billing shell (lot 7501)
    assert v["status"] == "excluded"
    assert "condominium billing lot" in v["reason"] and "unit lots" in v["reason"]


def test_condo_unit_lot_deliberate_branch(client):
    v = _validate(client, bbl="1012801001")                  # class-4 RB unit, present in parcels
    assert v["status"] == "excluded"
    assert "condominium unit lot" in v["reason"]             # deliberate, not incidental no-coords


def test_plain_non_class4_keeps_generic_message(client):
    v = _validate(client, bbl=NON_CLASS4)
    assert v["reason"] == "excluded: not tax class 4"


def test_non_r_highlot_gets_lot_range_reason_not_condo_label(client):
    # 200 Park (1012809010): non-R class, lot 9010 — excluded by the auto engine's lot-range
    # rule, but it is NOT a condo unit, and the reason must not claim it is.
    v = _validate(client, bbl="1012809010")
    assert v["status"] == "excluded"
    assert "condominium unit lot" not in v["reason"]
    assert "lot range (1001+)" in v["reason"] and "auto screen's comp rules" in v["reason"]
    # while the R-class unit lot keeps the true condo-unit message
    u = _validate(client, bbl="1012801001")
    assert "condominium unit lot" in u["reason"]
