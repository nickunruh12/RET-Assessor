"""API + view-model tests. Skipped if the DB isn't built. The geocode network step is
not exercised here (BBL path); live geocoding is covered in scripts/validate_geocode.py.
"""
import re
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


def test_welcome_page_offers_both_modes(client):
    raw = client.get("/").text
    html = " ".join(raw.split())                                          # normalize line-wraps
    assert "screens a New York City commercial property" in html         # blurb
    assert "no invented numbers and no verdicts" in html
    # both named modes are live front-door options (custom comps is no longer "coming soon")
    assert 'href="/screen?mode=auto_generate"' in raw                    # auto-generate mode link
    assert 'href="/custom"' in raw                                       # custom-comps flow link
    assert "Auto-generate comps" in html and "Use my own comps" in html
    # welcome is the front door, NOT the screening form (no lookup fields / no property-type select)
    assert 'name="bbl"' not in raw and 'name="borough"' not in raw


def test_get_started_enters_auto_generate_mode_and_screens(client):
    # Entering via the mode link screens exactly as before (mode wrapper doesn't change results).
    j_mode = client.get("/api/screen", params={"bbl": "1000090001", "mode": "auto_generate"}).json()
    j_plain = client.get("/api/screen", params={"bbl": "1000090001"}).json()
    assert j_mode["status"] == "ok"
    import json as _json
    assert _json.dumps(j_mode, sort_keys=True, default=str) == _json.dumps(j_plain, sort_keys=True, default=str)
    # an unknown mode falls back to auto_generate (safe default) -> identical output
    j_bad = client.get("/api/screen", params={"bbl": "1000090001", "mode": "nonsense"}).json()
    assert _json.dumps(j_bad, sort_keys=True, default=str) == _json.dumps(j_plain, sort_keys=True, default=str)


def test_screen_form_carries_mode(client):
    # the lookup form preserves the mode so a future custom_comps mode persists across re-runs
    html = client.get("/screen", params={"mode": "auto_generate"}).text
    assert '<input type="hidden" name="mode" value="auto_generate">' in html


def test_partial_address_surfaces_missing_inputs_refusal_not_blank(client):
    # house+street present, borough AND zip blank -> visible refusal (not a blank page),
    # reusing the existing missing_inputs path/message.
    j = client.get("/api/screen",
                   params={"house_number": "100", "street": "BROADWAY"}).json()
    assert j["status"] == "refused" and j["reason"] == "missing_inputs"
    assert "borough or ZIP" in j["message"] and "multiple boroughs" in j["message"]


def test_partial_address_refusal_renders_and_retains_inputs(client):
    html = client.get("/screen", params={"house_number": "100", "street": "BROADWAY"}).text
    assert "refusal" in html                                    # refusal box rendered
    assert _field(html, "house_number") == "100"                # typed values retained
    assert _field(html, "street") == "BROADWAY"


def test_partial_address_only_one_field_also_refuses(client):
    # any single address field typed but requirement unmet -> missing_inputs (not blank)
    j = client.get("/api/screen", params={"borough": "Manhattan"}).json()
    assert j["status"] == "refused" and j["reason"] == "missing_inputs"


def test_truly_empty_submit_is_clean_no_input_not_refusal(client):
    j = client.get("/api/screen", params={}).json()
    assert j == {"status": "no_input"}                          # None sentinel preserved
    html = client.get("/screen", params={}).text
    assert "refusal" not in html                                # no refusal box on empty


def test_dense_subject_full_view(client):
    j = client.get("/api/screen", params={"bbl": "1000090001"}).json()
    assert j["status"] == "ok"
    assert [s["key"] for s in j["signals"]] == \
        ["assessed_value_market", "mv_per_gross_sf", "tax_bill", "tax_per_gross_sf"]
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


def test_commercial_condo_gets_specific_message_others_stay_generic(client):
    # Condo (R-code) refuses with the specific plain-English explanation; behavior unchanged
    # (status refused, reason still out_of_scope_v1). Other out-of-scope classes stay generic.
    condo = client.get("/api/screen", params={"bbl": "3024131120"}).json()   # RG condo
    assert condo["status"] == "refused" and condo["reason"] == "out_of_scope_v1"
    assert "commercial condominiums" in condo["message"] and "unit level" in condo["message"]

    import duckdb
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    try:
        for like in ("V%", "G%", "U%"):                 # non-condo out-of-scope classes
            bbl = con.execute(
                "SELECT parcel_id FROM parcels WHERE bldg_class LIKE ? LIMIT 1", [like]).fetchone()
            if not bbl:
                continue
            j = client.get("/api/screen", params={"bbl": bbl[0]}).json()
            assert j["status"] == "refused" and j["reason"] == "out_of_scope_v1"
            assert "Asset class not supported" in j["message"]       # generic, no class list
            assert "condominium" not in j["message"]                 # condo text does not leak
    finally:
        con.close()


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


# --- Part 1: input persistence (form reflects the screened parcel from the BBL) -------
def _field(html, name):
    m = re.search(rf'name="{name}"[^>]*value="([^"]*)"', html)
    if m:
        return m.group(1)
    # borough is a <select>: read the selected option's value (blank -> "")
    sel = re.search(rf'name="{name}"[^>]*>(.*?)</select>', html, re.S)
    if sel:
        opt = re.search(r'<option value="([^"]*)"[^>]*\bselected\b', sel.group(1))
        return opt.group(1) if opt else ""
    return None


def test_form_populates_address_for_bbl_entered(client):
    html = client.get("/screen", params={"bbl": "1013000001"}).text
    assert _field(html, "bbl") == "1013000001"
    assert _field(html, "house_number") == "230"
    assert _field(html, "street") == "PARK AVENUE"
    assert _field(html, "borough") == "Manhattan"
    # ZIP input deliberately removed (geocoder only ever used it as a borough substitute,
    # ignored when borough was present); borough is now the single, required disambiguator.
    assert _field(html, "zip") is None


def test_form_persists_address_on_radius_rerun_bbl_only(client):
    # URL carries only bbl + radius (no address params) — address must still populate.
    html = client.get("/screen", params={"bbl": "1013000001", "radius": "0.43"}).text
    assert _field(html, "house_number") == "230" and _field(html, "street") == "PARK AVENUE"
    assert _field(html, "borough") == "Manhattan"


def test_form_persists_on_refusal_page(client):
    # Tight radius -> refusal; the screened parcel's identity must still show in the form.
    html = client.get("/screen", params={"bbl": "4000790030", "radius": "0.1"}).text
    assert "refusal" in html
    assert _field(html, "bbl") == "4000790030"
    assert _field(html, "street") == "JACKSON AVENUE" and _field(html, "borough") == "Queens"


# --- Part 2: cross-borough composition note -------------------------------------------
def test_cross_borough_note_on_manual_override(client):
    j = client.get("/api/screen", params={"bbl": "4000790030", "radius": "2.0"}).json()
    note = j["cross_borough_note"]
    assert note and "Comp set spans boroughs" in note
    assert "Queens (subject borough)" in note and "Manhattan" in note


def test_cross_borough_note_fires_on_default_autoexpand(client):
    j = client.get("/api/screen", params={"bbl": "1000220028"}).json()
    assert j["status"] == "ok"
    assert j["cross_borough_note"] and "Brooklyn" in j["cross_borough_note"]


def test_no_cross_borough_note_when_all_same_borough(client):
    j = client.get("/api/screen", params={"bbl": "1013000001"}).json()
    assert j["cross_borough_note"] is None


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


def test_variance_rows_have_two_psf_columns_no_raw_emv(client):
    j = client.get("/api/screen", params={"bbl": "1013000001"}).json()
    row = j["variance"]["views"][0]["rows"][0]
    assert "emv_psf_vs_subject" in row and "tax_psf_vs_subject" in row
    assert "emv_vs_subject" not in row          # raw market-value column removed
    assert "PSF" in row["emv_psf_vs_subject"] and "PSF" in row["tax_psf_vs_subject"]


def test_most_different_sorted_by_emv_psf(client):
    j = client.get("/api/screen", params={"bbl": "1013000001"}).json()
    md = next(v for v in j["variance"]["views"] if "Most Different" in v["name"])
    assert "market value per square foot" in md["dimension"]   # plain-English ordered-by label
    mags = [abs(r["emv_psf_pct_diff"]) for r in md["rows"] if r["emv_psf_pct_diff"] is not None]
    assert mags == sorted(mags, reverse=True)


def test_no_sf_subject_renders_psf_na(client):
    j = client.get("/api/screen", params={"bbl": "3053480042"}).json()
    row = j["variance"]["views"][0]["rows"][0]
    assert row["emv_psf_vs_subject"] == "n/a" and row["tax_psf_vs_subject"] == "n/a"


def test_radius_tighten_below_min_refuses_at_selected_radius(client):
    # Fallback subject (8 comps only at 1.0 mi). At 0.25 mi it has < 8 -> refuse, do not
    # silently widen back out.
    j = client.get("/api/screen", params={"bbl": "2023070046", "radius": "0.25"}).json()
    assert j["status"] == "refused" and j["reason"] == "insufficient_comps_within_cap"
    assert "selected radius" in j["message"] and "0.25" in j["message"]


def test_radius_widen_returns_more_via_api(client):
    base = client.get("/api/screen", params={"bbl": "1000090001"}).json()["comp_meta"]["comp_count"]
    wide = client.get("/api/screen",
                      params={"bbl": "1000090001", "radius": "2.0"}).json()["comp_meta"]["comp_count"]
    assert wide >= base


def test_radius_used_display_matches_applied(client):
    j = client.get("/api/screen", params={"bbl": "1000090001", "radius": "0.5"}).json()
    assert j["comp_meta"]["radius_used_miles"] == 0.5
    assert j["radius_control"]["selection"] == "0.5"


def test_radius_default_keeps_auto_behavior(client):
    j = client.get("/api/screen", params={"bbl": "1000090001"}).json()
    rc = j["radius_control"]
    assert rc["selection"] == "default" and rc["mode"] == "auto" and rc["handle"] == 0.5


def test_radius_override_mode_and_handle(client):
    rc = client.get("/api/screen",
                    params={"bbl": "1000090001", "radius": "0.7"}).json()["radius_control"]
    assert rc["mode"] == "override" and rc["handle"] == 0.7


def test_comp_count_endpoint_is_lightweight(client):
    j = client.get("/api/comp_count", params={"bbl": "1000090001", "radius": "0.5"}).json()
    assert set(j) >= {"radius", "count", "below_min", "min_comp_count"}
    assert "signals" not in j and "variance" not in j     # count only, no full payload
    assert j["radius"] == 0.5 and isinstance(j["count"], int)


def test_comp_count_below_min_in_dead_zone(client):
    # Fallback subject: at 0.25 mi fewer than 8 qualify -> below_min flagged, count > 0.
    j = client.get("/api/comp_count", params={"bbl": "2023070046", "radius": "0.25"}).json()
    assert j["below_min"] is True and j["count"] < 8


def test_comp_count_wide_at_least_tight(client):
    tight = client.get("/api/comp_count",
                       params={"bbl": "1000090001", "radius": "0.3"}).json()["count"]
    wide = client.get("/api/comp_count",
                      params={"bbl": "1000090001", "radius": "2.0"}).json()["count"]
    assert wide >= tight


def test_dispersion_present_on_each_nonrefused_signal(client):
    j = client.get("/api/screen", params={"bbl": "1013000001"}).json()
    for sig in j["signals"]:
        assert sig["refused"] is False
        d = sig["dispersion"]
        assert d is not None
        assert d["sd_band"].startswith("±1 SD: ")
        assert d["iqr"].startswith("Middle 50% of comps: ")
        assert d["cv"].startswith("Relative spread (CV): ")


def test_mean_shown_before_median_and_consistent_with_band(client):
    j = client.get("/api/screen", params={"bbl": "2023070046"}).json()
    for sig in j["signals"]:
        assert sig["mean"] is not None
        band = sig["dispersion"]["sd_band"]
        lo, hi = (float(p.replace("$", "").replace(",", ""))
                  for p in band.split(": ")[1].split(" (")[0].split(" – "))
        sd = float(band.split("(SD ")[1].rstrip(")").replace("$", "").replace(",", ""))
        # The UPPER bound and SD stay consistent with the visible mean (mean + SD == upper).
        # The LOWER bound is clamped non-negative (FIX 5), so it may sit above mean-SD but
        # never below zero — a value/tax/per-SF figure cannot be negative.
        tol = 0.01 if "gross_sf" in sig["unit"] else 1.0
        assert abs(sig["mean"] + sd - hi) < tol
        assert 0 <= lo <= hi
    html = client.get("/screen", params={"bbl": "2023070046"}).text
    assert html.index("Mean:") < html.index("Median:")     # mean sits before median on line 1


def test_sd_band_lower_bound_clamped_at_observed_minimum():
    # FIX 5 (pure unit) — on a right-skewed pool mean−1 SD is negative; the displayed lower
    # bound is clamped at the observed minimum (a real, positive comp value), never below it.
    from screener.serialize import _dispersion_stats
    vals = [100.0, 100.0, 120.0, 150.0, 5000.0]               # mean 1094, mean−SD < 0
    band = _dispersion_stats(vals, "$")["sd_band"]
    lo = float(band.split(": ")[1].split(" – ")[0].replace("$", "").replace(",", ""))
    assert lo == 100.0                                         # clamped to observed minimum
    assert "(SD $" in band                                    # the SD value is still shown


def test_dispersion_none_when_signal_refused(client):
    # no-SF subject -> per-SF signal refused -> no dispersion for it; the other two still have it
    j = client.get("/api/screen", params={"bbl": "3053480042"}).json()
    by_key = {s["key"]: s for s in j["signals"]}
    assert by_key["mv_per_gross_sf"]["dispersion"] is None
    assert by_key["assessed_value_market"]["dispersion"] is not None
    assert by_key["tax_bill"]["dispersion"] is not None


def test_per_sf_dispersion_uses_same_excluded_list_as_distribution(client):
    j = client.get("/api/screen", params={"bbl": "2023070046"}).json()
    sig = next(s for s in j["signals"] if s["key"] == "mv_per_gross_sf")
    # dispersion is computed from the chart's value list, so the n that frames it is the
    # SAME per-SF n (no-SF comps already excluded there).
    assert len(sig["distribution"]) == sig["n"]
    assert sig["dispersion"] is not None


def test_dispersion_caveat_rendered_once_in_html(client):
    html = client.get("/screen", params={"bbl": "1013000001"}).text
    assert html.count('class="src dispersion-caveat"') == 1   # rendered exactly once
    assert "sensitive to extreme values" in html
    assert "outlier" not in html.lower()                      # banned word stays out


def test_re_taxes_matches_tax_bill_subject_value(client):
    """Subject RE-taxes line == the Tax Bill chart's subject value (same derived figure)."""
    j = client.get("/api/screen", params={"bbl": "1012770027"}).json()
    re_taxes = j["subject"]["real_estate_taxes"]
    tax_sig = next(s for s in j["signals"] if s["key"] == "tax_bill")
    assert abs(re_taxes - tax_sig["subject_value"]) < 1.0


def test_tax_per_gba_twin_mirrors_mv_per_gba(client):
    # The tax-per-GBA chart mirrors the EMV-per-GBA chart exactly: same population filter,
    # same PLUTO GBA citation, same refusal + land-dominant guards. Labeled GBA, never GLA.
    j = client.get("/api/screen", params={"bbl": "1000090001"}).json()
    by = {s["key"]: s for s in j["signals"]}
    tx, mv = by["tax_per_gross_sf"], by["mv_per_gross_sf"]
    assert tx["n"] == mv["n"]                                       # same comp filter
    assert tx["sf_source_label"] == mv["sf_source_label"]           # PLUTO GBA citation
    assert "Gross Building Area" in tx["label"] and "GLA" not in tx["label"]
    assert j["provenance"]["signal_fields"]["Tax Bill Per Gross Building Area"].startswith("curtxbtot")
    # no-SF subject: BOTH twins refuse, same reason
    n = client.get("/api/screen", params={"bbl": "3053480042"}).json()
    byn = {s["key"]: s for s in n["signals"]}
    assert byn["tax_per_gross_sf"]["refused"] and byn["mv_per_gross_sf"]["refused"]
    assert byn["tax_per_gross_sf"]["refusal_reason"] == byn["mv_per_gross_sf"]["refusal_reason"]
    # industrial land-dominant comp: both twins exclude the SAME count and disclose.
    # (Pooled industrial subject whose comp set contains a land-dominant parcel; the exact
    # count is incidental — the invariant is that the two per-GBA twins mirror each other.)
    i = client.get("/api/screen", params={"bbl": "1000720013"}).json()
    byi = {s["key"]: s for s in i["signals"]}
    assert (byi["tax_per_gross_sf"]["land_dominant_excluded"]
            == byi["mv_per_gross_sf"]["land_dominant_excluded"] >= 1)
    assert "land-dominant" in byi["tax_per_gross_sf"]["land_dominant_note"]
