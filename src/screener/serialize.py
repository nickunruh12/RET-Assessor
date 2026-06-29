"""View-model builders: turn the already-built, already-validated engine outputs into
the structured dict the page renders. NO new engine logic — pure assembly + the raw
per-signal distributions the neutral charts need.

Every refusal state (out-of-scope, tax-exempt, insufficient comps, no-SF, address not
found) becomes a clear message, never a blank. Provenance travels on every figure.
"""
from __future__ import annotations

import statistics

import duckdb

from . import config
from .comps import REFUSAL_MESSAGES, CompSet, refusal_message, select_comps
from .geocode import RESOLVER_MESSAGES, ResolveResult
from .jurisdiction import CompCriteria, Jurisdiction
from .stats import compute_stats
from .abatements import icap_vintage
from .variance import compute_variance

DISCLAIMER = ("This is a descriptive screen of published assessment data — "
              "not a verdict, not tax advice, not an appraisal.")

# CONTEXT panel — cited, display-only, visually separated from the SIGNAL section.
CONTEXT = {
    "heading": "Context (Background Only — Not a Verdict, Not Advice)",
    "items": [
        {"label": "How Class-4 Is Valued",
         "text": "NYC DOF values class-4 (commercial) property primarily by income "
                 "(capitalized net operating income), not by price per square foot. This "
                 "screen compares published figures across nearby peers; it does not "
                 "reproduce the assessor's method.",
         "source": "NYC DOF — Determining Your Assessed Value",
         "url": "https://www.nyc.gov/site/finance/property/property-determining-your-assessed-value.page"},
        {"label": "Class-4 Assessment Ratio",
         "text": "Assessed value is set at 45% of market value for class 4.",
         "source": "NYC DOF — Determining Your Assessed Value",
         "url": "https://www.nyc.gov/site/finance/property/property-determining-your-assessed-value.page"},
        {"label": "FY2026 Class-4 Tax Rate",
         "text": "10.848%, applied to the transitional taxable value.",
         "source": "NYC DOF — Property Tax Rates",
         "url": "https://www.nyc.gov/site/finance/taxes/property-tax-rates.page"},
        {"label": "Appeals",
         "text": "Assessment challenges are filed with the NYC Tax Commission, which sets "
                 "an annual filing deadline. Confirm the current deadline on their site.",
         "source": "NYC Tax Commission",
         "url": "https://www.nyc.gov/site/taxcommission/index.page"},
    ],
}


# Radius control (comp-selection parameter). Two distinct modes:
#  * AUTO (default): the tool chooses — start 0.5, auto-expand to 1.0 mi cap, min 8.
#  * OVERRIDE (the slider): a continuous radius in [RADIUS_MIN, RADIUS_MAX]; fixed, no
#    auto-widen. The slider handle rests at RADIUS_REST.
RADIUS_MIN, RADIUS_MAX, RADIUS_REST = 0.1, 2.0, 0.5

# Gap magnitude below this (as a fraction of actual assessed) reads as "fully phased in".
PHASE_IN_ZERO_EPS = 0.005

# Item 4 — descriptive caveat by the Tax Bill chart. No calculation, no verdict.
TAX_BILL_CAVEAT = ("Tax bills reflect current transitional (phased-in) values; buildings "
                   "mid-phase-in may show temporarily lower bills than their fully-phased level.")

# Item 1 — clarifying line under the tax-methodology derivation (static, no verdict).
TAX_METHOD_NOTE = ("The tax is levied on the transitional (taxable) value, not on the 45% "
                   "actual assessed value. During a phase-in the two differ (see Phase-In "
                   "Note). This bill is the statutory amount before any ICAP, J-51, or PILOT "
                   "abatement.")

# Item 2 — comp statutory-basis caveat (static, always shown under the Tax Bill chart).
COMP_BASIS_CAVEAT = ("Comp tax bills are the statutory amount (transitional taxable value × "
                     "rate) computed identically for every comp. Comps on an abatement may "
                     "pay less than the figure shown. The uniform basis is intentional, so "
                     "comps are compared on the same fully-taxed footing.")

# Item 3 — PILOT caveat (static, ALWAYS shown; PILOT is not detectable from available data).
PILOT_CAVEAT = ("Some major office properties (for example Hudson Yards, the World Trade "
                "Center, Battery Park City) pay a negotiated PILOT instead of standard "
                "property tax. The tool cannot identify PILOT parcels, so a PILOT building's "
                "plotted tax bill may not reflect what it actually pays.")

# Item 5 — ICAP subject banner (conditional: only when the SUBJECT BBL has a current ICAP).
ICAP_BANNER = ("This parcel carries an ICAP property tax abatement. The tax bill shown is "
               "the statutory amount before that abatement; the owner's actual tax is lower "
               "for the abatement term. ICAP is a credit against the tax, not a reduction of "
               "assessed value.")


def _tax_methodology(subject: dict, rate: float) -> dict | None:
    """Item 1 — the published derivation chain that reconciles to the displayed Tax Bill.
    Every figure is a PUBLISHED roll value (or the statutory rate); nothing is recomputed
    differently from the chart. The 45% actual-assessed line is shown for transparency only
    — it is NOT a signal and nothing is compared off it."""
    mkt, act, txb = subject.get("curmkttot"), subject.get("curacttot"), subject.get("curtxbtot")
    if txb is None:
        return None
    return {
        "market_value": mkt, "market_value_display": _signal_num(mkt, "$"),
        "actual_assessed": act, "actual_assessed_display": _signal_num(act, "$"),
        "transitional": txb, "transitional_display": _signal_num(txb, "$"),
        "rate_pct": f"{rate * 100:g}%",
        "tax_bill": txb * rate, "tax_bill_display": _signal_num(txb * rate, "$"),
        "note": TAX_METHOD_NOTE,
    }


def _f(x, nd=2):
    return None if x is None else round(float(x), nd)


def _compact_dollars(x):
    """Sign-aware compact dollar figure for phase-in gaps: '$13.2M', '-$9.8M', '$450k'.
    n/a when missing — never zeroed."""
    if x is None:
        return "n/a"
    sign, a = ("-" if x < 0 else ""), abs(x)
    if a >= 1e6:
        return f"{sign}${a / 1e6:,.1f}M"
    if a >= 1e3:
        return f"{sign}${a / 1e3:,.0f}k"
    return f"{sign}${a:,.0f}"


def _phase_in_bucket(curacttot, curtrntot) -> str | None:
    """Comp Phase-In Gap cell: '$1.2M (Ramping Up)' etc. ONLY a subtraction of two
    published roll values + a sign bucket. None -> 'n/a' (never zeroed). Threshold:
    |gap| within 0.5% of actual assessed = Fully Phased."""
    if curacttot is None or curtrntot is None or not curacttot:
        return None
    gap = curacttot - curtrntot
    frac = gap / curacttot
    bucket = ("Ramping Up" if frac > PHASE_IN_ZERO_EPS
              else "Ramping Down" if frac < -PHASE_IN_ZERO_EPS else "Fully Phased")
    return f"{_compact_dollars(gap)} ({bucket})"


def _transitional_series_points(subject: dict) -> list[dict]:
    """The subject's transitional-taxable (curtxbtot) series, one entry PER roll year in the
    window (oldest→newest), each: {year, status, display, value, pct_from_prev}.

      status 'value'     — published Final-roll value for that year
             'tentative' — newest year's Final not out yet; Tentative (period 1) used, labeled
             'exempt'    — a real $0 (fully-exempt parcel-year) — distinct from a gap
             'gap'       — NO Final-roll class-4 row that year (missing; never zero/interpolated)

    Percent change is shown only between two CONSECUTIVE calendar years that both have a usable
    numeric value (prior > 0) — never spanning a gap, never dividing by zero. Pulls from the
    subject's pre-attached `taxable_series` (loader-built); falls back to the single current-year
    point (curtxbtot @ roll_year) if that table is unavailable, so nothing breaks without it."""
    series = subject.get("taxable_series") or []
    by_year = {p["year"]: p for p in series}
    if not by_year:
        # graceful fallback (series table absent): just the current roll year, if known.
        try:
            ry = int(subject.get("roll_year"))
        except (TypeError, ValueError):
            return []
        txb = subject.get("curtxbtot")
        if txb is None:
            return []
        return [{"year": ry, "status": "value", "display": f"${_signal_num(txb, '$')}",
                 "value": txb, "pct_from_prev": None}]

    out, prev_val = [], None
    for y in sorted(int(w) for w in config.ROLL_YEAR_WINDOW):
        p = by_year.get(y)
        if p is None:
            out.append({"year": y, "status": "gap", "display": "—", "value": None,
                        "pct_from_prev": None})
            prev_val = None                       # a gap breaks the consecutive-year chain
            continue
        val = p.get("value")
        if p.get("exempt") or val == 0:
            entry = {"year": y, "status": "exempt", "display": "$0 (exempt)", "value": 0.0}
        else:
            tentative = str(p.get("period")) != "3"
            entry = {"year": y, "value": val,
                     "status": "tentative" if tentative else "value",
                     "display": f"${_signal_num(val, '$')}" + (" (tentative)" if tentative else "")}
        cur = entry["value"]
        entry["pct_from_prev"] = (_signed_pct((cur - prev_val) / prev_val * 100)
                                  if (prev_val and prev_val > 0 and cur is not None) else None)
        out.append(entry)
        prev_val = cur
    return out


def _phase_in_note(phase, subject: dict) -> dict:
    """Phase-In Note: readable mechanism + SUBJECT pending-increase (item 1/3) + realized
    transitional change as a LABELED year-by-year series (item 2/4). Every number is a
    subtraction of two PUBLISHED roll values or a published prior-year value — no
    projection, no schedule, never ÷5. The sign-aware meaning (ramping up / phasing down /
    fully phased) is carried by the labeled pending line below — not explained twice."""
    v = phase.subject_value

    # Item 1/3 — SUBJECT pending change = actual assessed − transitional assessed (published),
    # rendered with the "Transitional Value vs. Assessed Value Gap =" label prefix; the
    # sign-aware wording (ramping-up / phasing-down / fully-phased) switches on the gap sign.
    act, trn = subject.get("curacttot"), subject.get("curtrntot")
    PENDING_PREFIX = "Transitional Value vs. Assessed Value Gap"
    if act is None or trn is None:
        pending = {"prefix": PENDING_PREFIX, "display": "n/a",
                   "label": "approximate taxable-value increase still pending under phase-in",
                   "caveat": None}
    else:
        gap = act - trn
        frac = gap / act if act else 0.0
        if frac > PHASE_IN_ZERO_EPS:
            label = "approximate taxable-value increase still pending under phase-in"
            caveat = "This amount phases in over the remaining years, not all at once."
        elif frac < -PHASE_IN_ZERO_EPS:
            label = ("amount by which the transitional (taxable) value currently exceeds the "
                     "actual assessed value (phasing down)")
            caveat = "This difference phases out over the remaining years, not all at once."
        else:
            label = "effectively fully phased in — no material pending change"
            caveat = None
        pending = {"prefix": PENDING_PREFIX, "display": _compact_dollars(gap),
                   "label": label, "caveat": caveat}

    # Item 2/4 — REALIZED transitional-taxable values as a LABELED, year-by-year SERIES across
    # the roll-year window (2023–2027). Each year shows the subject's Final-roll curtxbtot with
    # the consecutive-year percent change; gaps render as gaps, exempt as $0/exempt — never
    # zeroed or interpolated. Subject-only: the comp comparison stays single-year (see note).
    years = _transitional_series_points(subject)
    if not years:
        realized = {"available": False,
                    "message": ("transitional (taxable) value not available — the year-by-year "
                                "series cannot be shown")}
    else:
        realized = {"available": True,
                    "years": years,
                    "year_labels": [y["year"] for y in years if y["status"] != "gap"],
                    "scope_note": ("Subject's transitional (taxable) value by roll year. The "
                                   "comp-median comparison below stays single-year; a multi-year "
                                   "comp median is not shown, since comp-set membership and n "
                                   "shift from year to year."),
                    "framing": ("Realized transitional (taxable) value by roll year — descriptive "
                                "history, not a forecast. The pending figure above is the amount "
                                "still legally committed to phase in.")}

    return {
        "title": "Phase-In Note",
        "formula": "(actual assessed value − transitional assessed value) ÷ actual assessed value",
        "subject_value": _f(v, 2),
        "median": _f(phase.median, 2),
        "n": phase.n,
        "pending": pending,
        "realized_yoy": realized,
        "footer": "Descriptive only — not a verdict on the assessment.",
    }


def _zip5(z) -> str:
    """First five digits of a ZIP (drops ZIP+4, dashes, whitespace). '' if none."""
    return "".join(ch for ch in str(z or "") if ch.isdigit())[:5]


def _reconciliation_note(resolve: ResolveResult | None, subject: dict) -> str | None:
    """Descriptive override note (NO refusal): shown only when a user-typed ZIP or borough
    conflicts with the resolved parcel's PUBLISHED value, so a wrong match is catchable.
    None on a clean search (correct value, or value omitted, or a BBL-only run)."""
    if resolve is None:
        return None
    parts = []
    uz, pz = _zip5(resolve.zip_code), _zip5(subject.get("zip_code"))
    if uz and pz and uz != pz:
        parts.append(f"You searched ZIP {uz}. The matching parcel's published ZIP is {pz}.")
    ub = (resolve.borough or "").strip()
    pb = str(subject.get("borough") or "").strip()
    if ub and pb and ub.lower() != pb.lower():
        parts.append(f"You searched borough {ub}. The matching parcel's published borough is {pb}.")
    return (" ".join(parts) + " Confirm this is the correct building.") if parts else None


def _subject_panel(subject: dict | None, resolve: ResolveResult | None,
                   rate: float | None = None) -> dict | None:
    if subject is None:
        return None
    # Identity line is built ONLY from the resolved parcel's PUBLISHED fields (roll address
    # primary, PLUTO fallback) — never the user-typed house/street/borough/ZIP. The ZIP shown
    # here and on the Borough/ZIP row are therefore the SAME published value.
    roll = " ".join(x for x in [subject.get("house_number"), subject.get("street_name")] if x).strip()
    loc = subject.get("borough") or (f"ZIP {subject.get('zip_code')}" if subject.get("zip_code") else None)
    addr = ", ".join([b for b in [roll, loc] if b]) or subject.get("pluto_address") or None
    # Real estate taxes — the SAME derived figure used for the Tax Bill chart
    # (curtxbtot x rate). Not recomputed differently.
    txb = subject.get("curtxbtot")
    re_taxes = (txb * rate) if (rate is not None and txb is not None) else None
    return {
        "address": addr,
        "has_icap": bool(subject.get("has_icap")),
        "reconciliation_note": _reconciliation_note(resolve, subject),
        "bbl": subject.get("parcel_id"),
        "bldg_class": subject.get("bldg_class"),
        "bucket_label": subject.get("bucket_label"),
        "borough": subject.get("borough"),
        "zip_code": subject.get("zip_code"),
        "gross_sf": subject.get("sf"),
        "sf_source": subject.get("sf_source"),
        "year_built": subject.get("year_built"),
        "year_built_missing": subject.get("year_built") in (None, "", "0"),
        "assessed_market_value": subject.get("curmkttot"),
        "real_estate_taxes": re_taxes,
    }


_SF_SOURCE_LABEL = {
    "pluto_bldgarea": "based on gross building area (PLUTO)",
    "roll_gross_sqft_fallback": "based on gross building area (DOF assessment roll)",
}


def _signal_distributions(cs: CompSet, rate: float) -> dict[str, list[float]]:
    """The raw comp values each chart plots (subject is added on the page, never here)."""
    return {
        "assessed_value_market": [c.curmkttot for c in cs.comps if c.curmkttot is not None],
        "tax_bill": [c.curtxbtot * rate for c in cs.comps if c.curtxbtot is not None],
        "mv_per_gross_sf": [c.curmkttot / c.sf for c in cs.comps
                            if c.sf and c.curmkttot is not None],
    }


def _signal_num(v, unit):
    """Display a signal value: PSF (division) -> 2 dp; whole-dollar figures -> 0 dp."""
    if v is None:
        return "n/a"
    return f"{v:,.2f}" if "gross_sf" in unit else f"{v:,.0f}"


# Reliability caveat — rendered ONCE, light font. "outlier" is a banned word (render_check),
# so the meaning is preserved as "sensitive to extreme values".
DISPERSION_CAVEAT = ("Standard deviation and CV reflect this comp set (n shown); small sets "
                     "are sensitive to extreme values. The middle-50% range is more robust "
                     "on thin pools.")


def _money(v, unit):
    """Dollar/PSF figure WITH a $ sign for the dispersion sub-line: PSF -> 2 dp, whole-dollar
    -> 0 dp. Sign-aware so a ±1 SD lower bound below zero reads '-$X', not '$-X'."""
    if v is None:
        return "n/a"
    nd = 2 if "gross_sf" in unit else 0
    return f"{'-' if v < 0 else ''}${abs(v):,.{nd}f}"


def _dispersion_stats(values: list[float], unit: str) -> dict | None:
    """Descriptive spread for ONE distribution, in its own units, computed from the SAME comp
    value list that feeds that chart (the per-SF list already excludes no-SF comps). Three
    metrics only — POPULATION SD band, interquartile range, coefficient of variation. No
    variance/mode/z-score/CI; no projection, inference, or verdict."""
    vals = [float(v) for v in values]
    if len(vals) < 2:
        return None
    mean = statistics.fmean(vals)
    sd = statistics.pstdev(vals)                                  # POPULATION standard deviation
    q1, _q2, q3 = statistics.quantiles(vals, n=4, method="inclusive")  # 25th / 75th percentile
    cv = "n/a" if mean <= 0 else f"{sd / mean * 100:.2f}%"        # guard: never divide by mean<=0
    return {
        "sd_band": f"±1 SD: {_money(mean - sd, unit)} – {_money(mean + sd, unit)} (SD {_money(sd, unit)})",
        "iqr": f"middle 50% of comps: {_money(q1, unit)} – {_money(q3, unit)}",
        "cv": f"relative spread (CV): {cv}",
    }


def _signal_view(sig, dist_values: list[float], extra: dict) -> dict:
    out = {
        "key": sig.key, "label": sig.label, "unit": sig.unit,
        "refused": sig.refused, "refusal_reason": sig.refusal_reason,
        "message": " ".join(sig.notes) if sig.refused else None,
        "n": sig.n, "excluded_blank": sig.excluded_blank,
        "mean": _f(sig.mean), "median": _f(sig.median),
        "minimum": _f(sig.minimum), "maximum": _f(sig.maximum), "stddev": _f(sig.stddev),
        "subject_value": _f(sig.subject_value), "subject_percentile": sig.subject_percentile,
        "distribution": [round(float(v), 4) for v in dist_values] if not sig.refused else [],
        "notes": sig.notes,
        # display strings (precision per item 2): whole $ -> 0 dp, PSF -> 2 dp, percentile -> 2 dp
        "subject_value_display": _signal_num(sig.subject_value, sig.unit),
        "mean_display": _signal_num(sig.mean, sig.unit),
        "median_display": _signal_num(sig.median, sig.unit),
        "minimum_display": _signal_num(sig.minimum, sig.unit),
        "maximum_display": _signal_num(sig.maximum, sig.unit),
        "subject_percentile_display": f"{sig.subject_percentile:.2f}" if sig.subject_percentile is not None else "n/a",
        # ±1 SD band, IQR, CV — computed from THIS chart's value list (None when refused).
        "dispersion": None if sig.refused else _dispersion_stats(dist_values, sig.unit),
    }
    out.update(extra)
    return out


def _display_address(d) -> tuple[str | None, str | None]:
    """Display address: roll (8y4t-faws) primary, PLUTO fallback. Cite the source used."""
    if d.house_number and d.street_name:
        return f"{str(d.house_number).strip()} {str(d.street_name).strip()}".strip(), "DOF roll (8y4t-faws)"
    if d.pluto_address:
        return d.pluto_address.strip(), "PLUTO"
    return None, None


def _signed_pct(x):
    """Percentages -> EXACTLY 2 dp. A genuine zero shows '0.00%' (never suppressed)."""
    if x is None:
        return None
    r = round(x, 2)
    return "0.00%" if r == 0 else f"{r:+.2f}%"


def _signed_dollar_psf(x):
    """Per-SF dollar delta -> EXACTLY 2 dp. A genuine zero shows '$0.00' (never suppressed)."""
    r = round(x, 2)
    if r == 0:
        return "$0.00"
    return f"{'-' if r < 0 else '+'}${abs(r):,.2f}"


def _delta_sf(abs_delta, pct):
    # Gross SF is a whole count (0 dp); the percent part is division-produced (2 dp).
    if abs_delta is None or pct is None:
        return "n/a"
    return f"{abs_delta:+,.0f} SF ({_signed_pct(pct)})"


def _psf(value, sf):
    return (value / sf) if (value is not None and sf) else None


def _delta_psf(abs_delta, pct):
    """'+$322.00 PSF (+93.12%)' / '$0.00 PSF (0.00%)' / 'n/a'. PSF $ and % both 2 dp."""
    if abs_delta is None or pct is None:
        return "n/a"
    return f"{_signed_dollar_psf(abs_delta)} PSF ({_signed_pct(pct)})"


def _variance_row(d, subj: dict, rate: float) -> dict:
    """One shared-layout attribute-diff row. Descriptive only; no causal language.

    The market-value and tax comparisons are PER GROSS SF (PSF) — no raw-dollar column.
    Comps without gross SF render 'n/a' in both PSF columns (never zeroed/fabricated).
    Display strings are formatted here so the template stays trivial."""
    address, address_source = _display_address(d)
    subj_sf = subj.get("sf")
    sf_abs = (d.sf - subj_sf) if (d.sf is not None and subj_sf) else None

    # EMV per gross SF (curmkttot / SF) vs subject.
    comp_emv_psf, subj_emv_psf = _psf(d.curmkttot, d.sf), _psf(subj.get("curmkttot"), subj_sf)
    emv_psf_abs = (comp_emv_psf - subj_emv_psf) if (comp_emv_psf is not None and subj_emv_psf) else None

    # Tax per gross SF ((curtxbtot x rate) / SF) vs subject — same derived tax figure.
    comp_tax = d.curtxbtot * rate if d.curtxbtot is not None else None
    subj_tax = subj["curtxbtot"] * rate if subj.get("curtxbtot") is not None else None
    comp_tax_psf, subj_tax_psf = _psf(comp_tax, d.sf), _psf(subj_tax, subj_sf)
    tax_psf_abs = (comp_tax_psf - subj_tax_psf) if (comp_tax_psf is not None and subj_tax_psf) else None
    tax_psf_pct = ((comp_tax_psf - subj_tax_psf) / subj_tax_psf * 100) \
        if (comp_tax_psf is not None and subj_tax_psf) else None

    exact = d.match_type == "exact"
    return {
        "parcel_id": d.citation.parcel_id,
        "address": address or "n/a", "address_source": address_source,
        "stories_display": "n/a" if d.stories in (None, 0) else f"{d.stories:,.0f}",
        "comp_sf_display": "n/a" if d.sf is None else f"{d.sf:,.0f}",
        "sf_vs_subject": _delta_sf(sf_abs, d.sf_pct_diff),
        "year_built_display": "n/a" if d.year_built_missing else d.year_built,
        "exact_match_display": "✓" if exact else f"✗ ({d.bldg_class})",
        "distance_display": f"{d.distance_miles:.2f}",
        "emv_psf_vs_subject": _delta_psf(emv_psf_abs, d.emv_psf_pct_diff),
        "tax_psf_vs_subject": _delta_psf(tax_psf_abs, tax_psf_pct),
        # Item 3 — Phase-In Gap (comp curacttot − curtrntot + sign bucket). Displayed
        # attribute ONLY: never filters/sorts/drops comps. 'n/a' if either value missing.
        "phase_in_gap_display": _phase_in_bucket(d.curacttot, d.curtrntot) or "n/a",
        # Item 5 — DISCLOSURE ONLY ICAP tag. Never filters/excludes the comp or alters its
        # plotted statutory tax.
        "has_icap": bool(getattr(d, "has_icap", False)),
        # raw values + provenance still travel per row (not rendered in the table cells)
        "stories": d.stories, "comp_sf": d.sf,
        "sf_abs_delta": sf_abs, "sf_pct_diff": d.sf_pct_diff,
        "emv_psf_pct_diff": d.emv_psf_pct_diff, "tax_psf_pct_diff": tax_psf_pct,
        "match_type": d.match_type, "bldg_class": d.bldg_class,
        "citation": d.citation.model_dump(mode="json"),
        "sf_dataset_version": d.sf_dataset_version,
    }


def _expense_section(juris, criteria, subject: dict) -> dict:
    """Expense Ratio Check section + the DYNAMIC benchmark note (config-driven).

    The note renders ONLY when a range exists for the subject's (metro, product_type).
    No range -> no note (never invented, never an empty placeholder)."""
    metro = criteria.metro_name
    product = juris.product_type(subject.get("bldg_class"), criteria)
    note = None
    rng = criteria.expense_ratio_benchmarks.get(metro, {}).get(product) if product else None
    if rng:
        lo, hi = rng
        article = "an" if product[:1].lower() in "aeiou" else "a"
        note = (f"{lo:.0f}–{hi:.0f}% = typical range for the real estate tax share of "
                f"operating expenses for {article} {product} building in {metro} "
                f"(general rule of thumb, not a sourced benchmark).")
    return {
        "section": "Expense Ratio Check",
        "metro": metro, "product_type": product, "benchmark_note": note,
    }


def _cross_borough_note(cs, juris) -> str | None:
    """Descriptive note when the comp set spans boroughs (any cross-borough comp, whether
    from default auto-expand or a manual radius override). None if all same-borough."""
    subj_boro = cs.subject.get("borough")
    counts: dict[str, int] = {}
    for c in cs.comps:
        b = juris.borough_of(c.citation.parcel_id)
        counts[b] = counts.get(b, 0) + 1
    others = sorted(((b, n) for b, n in counts.items() if b != subj_boro), key=lambda x: -x[1])
    if not others:
        return None
    n = len(cs.comps)
    parts = [f"{counts.get(subj_boro, 0)} of {n} comps in {subj_boro} (subject borough)"]
    parts += [f"{cnt} in {b}" for b, cnt in others]
    return ("Comp set spans boroughs: " + ", ".join(parts) +
            ". Comps outside the subject's borough may sit in a different submarket; "
            "interpret accordingly.")


def _radius_control(selection: str, show: bool) -> dict:
    mode = "auto" if selection == "default" else "override"
    handle = RADIUS_REST if mode == "auto" else float(selection)
    return {
        "mode": mode, "selection": selection, "handle": handle,
        "min": RADIUS_MIN, "max": RADIUS_MAX, "show": show,
    }


def _refused(stage, reason, message, *, subject=None, resolve=None, extra=None,
             radius_selection: str = "default") -> dict:
    # The radius control is only meaningful where a comp pool exists and radius can fix
    # the outcome — i.e. an insufficient-comps refusal (so the user can widen back).
    show = reason == "insufficient_comps_within_cap"
    out = {
        "status": "refused", "stage": stage, "reason": reason, "message": message,
        "disclaimer": DISCLAIMER, "context": CONTEXT,
        "subject": _subject_panel(subject, resolve),
        "rung3": {"enabled": False, "section": "Calculate Implied Cap Rate With User-Provided NOI"},
        "radius_control": _radius_control(radius_selection, show),
    }
    if extra:
        out.update(extra)
    return out


def build_screen_view(con: duckdb.DuckDBPyConnection, criteria: CompCriteria,
                      juris: Jurisdiction, *, bbl: str | None = None,
                      resolve: ResolveResult | None = None,
                      radius_selection: str = "default") -> dict:
    """Assemble the full page view model from a BBL (or a prior address resolution).

    `criteria` already carries any radius override; `radius_selection` is the label of
    the chosen radius ('default' or e.g. '0.5'), used for the control + refusal message.
    """
    # Address resolution refusal (out-of-scope, tax-exempt, address not found, …).
    if resolve is not None and not resolve.ok:
        return _refused("resolve", resolve.reason, resolve.message, resolve=resolve,
                        subject=None, radius_selection=radius_selection)
    subject_bbl = (resolve.bbl if resolve is not None else bbl)
    if not subject_bbl:
        return _refused("resolve", "missing_inputs", RESOLVER_MESSAGES["missing_inputs"],
                        radius_selection=radius_selection)

    cs = select_comps(con, subject_bbl, juris, criteria)
    if cs.refused:
        if cs.note == "insufficient_comps_within_cap" and radius_selection != "default":
            msg = (f"insufficient comparable properties at the selected radius "
                   f"({radius_selection} mi)")
        else:
            msg = refusal_message(cs.note) or REFUSAL_MESSAGES.get(cs.note) or cs.note
        return _refused("comps", cs.note, msg, subject=cs.subject, resolve=resolve,
                        radius_selection=radius_selection,
                        extra={"radius_used_miles": cs.radius_used_miles,
                               "candidates_within_cap": cs.candidates_within_cap})

    stats = compute_stats(cs, criteria)
    var = compute_variance(cs)
    dists = _signal_distributions(cs, criteria.class4_tax_rate)

    shared = {"radius_used_miles": cs.radius_used_miles, "comp_count": cs.count}
    signals = []
    for key in ("assessed_value_market", "tax_bill", "mv_per_gross_sf"):
        extra = dict(shared)
        if key == "mv_per_gross_sf":
            extra["sf_source_label"] = _SF_SOURCE_LABEL.get(cs.subject.get("sf_source"),
                                                            "based on gross building area")
        if key == "tax_bill":
            extra["caveat"] = TAX_BILL_CAVEAT          # item 4
        signals.append(_signal_view(stats.signals[key], dists[key], extra))

    phase = stats.signals["phase_in_gap"]

    # Provenance — fold the ICAP abatement vintage in beside the roll + PLUTO versions so
    # all three source vintages are visible together.
    abate_extractdt, abate_dataset = icap_vintage(con)
    provenance = dict(stats.provenance)
    provenance["abatement_dataset"] = abate_dataset
    provenance["abatement_extractdt"] = abate_extractdt

    subject_has_icap = bool(cs.subject.get("has_icap"))

    return {
        "status": "ok",
        "disclaimer": DISCLAIMER,
        "subject": _subject_panel(cs.subject, resolve, criteria.class4_tax_rate),
        # Item 1 — tax-methodology derivation; Items 2/3 — static caveats under the chart.
        "tax_methodology": _tax_methodology(cs.subject, criteria.class4_tax_rate),
        "comp_basis_caveat": COMP_BASIS_CAVEAT,
        "pilot_caveat": PILOT_CAVEAT,
        # Item 5 — ICAP subject banner (conditional). Cited to the abatement dataset + vintage.
        "icap_banner": ({"message": ICAP_BANNER, "dataset": abate_dataset,
                         "extractdt": abate_extractdt} if subject_has_icap else None),
        "comp_meta": {
            "comp_count": cs.count,
            "radius_used_miles": cs.radius_used_miles,
            "composition": {
                "exact_count": cs.exact_count, "adjacent_count": cs.adjacent_count,
                "adjacent_breakdown": cs.adjacent_breakdown,
                "fallback_triggered": cs.fallback_triggered,
            },
            "low_exact_caution": stats.low_exact_caution,
            "caution_message": stats.caution_message,
            "sf_band_applied": cs.sf_band_applied,
        },
        "signals": signals,
        "dispersion_caveat": DISPERSION_CAVEAT,
        "cross_borough_note": _cross_borough_note(cs, juris),
        "phase_in_note": _phase_in_note(phase, cs.subject),
        "variance": {
            "subject_sf": cs.subject.get("sf"),
            "subject_emv": cs.subject.get("curmkttot"),
            "subject_bldg_class": cs.subject.get("bldg_class"),
            "stories_column": True,                  # STEP A gate passed (NumFloors 99.83% fill)
            "views": [
                {"name": v.name, "dimension": v.dimension,
                 "rows": [_variance_row(d, cs.subject, criteria.class4_tax_rate) for d in v.rows]}
                for v in (var.views["nearest_by_distance"],
                          var.views["nearest_by_sf"],
                          var.views["most_different_by_assessed"])
            ],
            "all_diffs": [_variance_row(d, cs.subject, criteria.class4_tax_rate)
                          for d in var.all_diffs],
        },
        "provenance": provenance,
        "context": CONTEXT,
        "rung3": {"enabled": False, "section": "Calculate Implied Cap Rate With User-Provided NOI"},
        "expense_ratio": _expense_section(juris, criteria, cs.subject),
        "radius_control": _radius_control(radius_selection, show=True),
    }


def build_rung3_view(result) -> dict:
    """Serialize a Rung3Result into its partitioned, stamped section."""
    return {
        "partition": result.partition, "enabled": result.enabled, "computed": result.computed,
        "stamp": result.stamp, "statement": result.statement,
        "implied_cap_rate_pct": result.implied_cap_rate_pct,
        "user_noi": result.user_noi, "noi_source": result.noi_source,
        "market_value": result.market_value,
        "market_value_citation": result.market_value_citation,
        "rejected": result.rejected, "rejection_reason": result.rejection_reason,
        "message": result.message,
    }


def build_expense_ratio_view(result) -> dict:
    """Serialize an ExpenseRatioResult into its stamped section."""
    return {
        "partition": result.partition, "computed": result.computed,
        "statement": result.statement, "stamp": result.stamp,
        "ratio_pct": result.ratio_pct, "real_estate_taxes": result.real_estate_taxes,
        "user_opex": result.user_opex, "opex_source": result.opex_source,
        "rejected": result.rejected, "rejection_reason": result.rejection_reason,
        "message": result.message,
    }
