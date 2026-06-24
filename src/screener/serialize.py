"""View-model builders: turn the already-built, already-validated engine outputs into
the structured dict the page renders. NO new engine logic — pure assembly + the raw
per-signal distributions the neutral charts need.

Every refusal state (out-of-scope, tax-exempt, insufficient comps, no-SF, address not
found) becomes a clear message, never a blank. Provenance travels on every figure.
"""
from __future__ import annotations

import duckdb

from .comps import REFUSAL_MESSAGES, CompSet, refusal_message, select_comps
from .geocode import RESOLVER_MESSAGES, ResolveResult
from .jurisdiction import CompCriteria, Jurisdiction
from .stats import compute_stats
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


# Radius toggle (comp-selection parameter). Default = auto 0.5->1.0 mi; override fixes
# the search radius. Max stated to the user.
RADIUS_MIN, RADIUS_MAX = 0.25, 2.0
RADIUS_PRESETS = ["default", "0.25", "0.5", "0.75", "1.0", "1.5", "2.0"]

# Gap magnitude below this reads as "effectively fully phased in".
PHASE_IN_ZERO_EPS = 0.005


def _f(x, nd=2):
    return None if x is None else round(float(x), nd)


def _phase_in_note(phase) -> dict:
    """Phase-In Note: readable variable names + a SIGN-dependent MECHANISM sentence
    (not a verdict). Raw column names stay in the Provenance footer only."""
    v = phase.subject_value
    if v is None:
        mechanism = "The phase-in gap is unavailable for this parcel."
    elif v > PHASE_IN_ZERO_EPS:
        mechanism = ("A positive gap means the transitional (taxable) value is still below "
                     "the actual assessed value, so the taxable value is ramping up toward a "
                     "higher assessment over the phase-in period.")
    elif v < -PHASE_IN_ZERO_EPS:
        mechanism = ("A negative gap means the transitional (taxable) value currently sits "
                     "above the actual assessed value, so this year's tax is based on a value "
                     "higher than the latest assessment, ramping down over the phase-in period.")
    else:
        mechanism = "A gap near zero means the assessment is effectively fully phased in."
    return {
        "title": "Phase-In Note",
        "formula": "(actual assessed value − transitional assessed value) ÷ actual assessed value",
        "subject_value": _f(v, 3),
        "median": _f(phase.median, 3),
        "n": phase.n,
        "mechanism": mechanism,
        "footer": "Descriptive only — not a verdict on the assessment.",
    }


def _subject_panel(subject: dict | None, resolve: ResolveResult | None,
                   rate: float | None = None) -> dict | None:
    if subject is None:
        return None
    addr = None
    if resolve is not None:
        bits = [resolve.house_number, resolve.street]
        loc = resolve.borough or (f"ZIP {resolve.zip_code}" if resolve.zip_code else None)
        addr = ", ".join([b for b in [" ".join(x for x in bits if x), loc] if b]) or None
    # Real estate taxes — the SAME derived figure used for the Tax Bill chart
    # (curtxbtot x rate). Not recomputed differently.
    txb = subject.get("curtxbtot")
    re_taxes = (txb * rate) if (rate is not None and txb is not None) else None
    return {
        "address": addr,
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
    return None if x is None else f"{x:+.0f}%"


def _delta_sf(abs_delta, pct):
    if abs_delta is None or pct is None:
        return "n/a"
    return f"{abs_delta:+,.0f} SF ({_signed_pct(pct)})"


def _delta_emv(abs_delta, pct):
    if abs_delta is None or pct is None:
        return "n/a"
    sign = "-" if abs_delta < 0 else "+"
    return f"{sign}${abs(abs_delta):,.0f} ({_signed_pct(pct)})"


def _variance_row(d, subj: dict) -> dict:
    """One shared-layout attribute-diff row. Descriptive only; no causal language.

    Display strings are formatted here so the template stays trivial and the signed
    formatting is consistent. Blanks render as 'n/a' (never zeroed)."""
    address, address_source = _display_address(d)
    subj_sf = subj.get("sf")
    subj_emv = subj.get("curmkttot")
    sf_abs = (d.sf - subj_sf) if (d.sf is not None and subj_sf) else None
    emv_abs = (d.curmkttot - subj_emv) if (d.curmkttot is not None and subj_emv) else None
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
        "emv_vs_subject": _delta_emv(emv_abs, d.assessed_pct_diff),
        # raw values + provenance still travel per row (not rendered in the table cells)
        "stories": d.stories, "comp_sf": d.sf,
        "sf_abs_delta": sf_abs, "sf_pct_diff": d.sf_pct_diff,
        "emv_abs_delta": emv_abs, "emv_pct_diff": d.assessed_pct_diff,
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


def _radius_control(selection: str) -> dict:
    return {"selection": selection, "presets": RADIUS_PRESETS, "max_miles": RADIUS_MAX}


def _refused(stage, reason, message, *, subject=None, resolve=None, extra=None,
             radius_selection: str = "default") -> dict:
    out = {
        "status": "refused", "stage": stage, "reason": reason, "message": message,
        "disclaimer": DISCLAIMER, "context": CONTEXT,
        "subject": _subject_panel(subject, resolve),
        "rung3": {"enabled": False, "section": "Calculate Implied Cap Rate With User-Provided NOI"},
        "radius_control": _radius_control(radius_selection),
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
        signals.append(_signal_view(stats.signals[key], dists[key], extra))

    phase = stats.signals["phase_in_gap"]

    return {
        "status": "ok",
        "disclaimer": DISCLAIMER,
        "subject": _subject_panel(cs.subject, resolve, criteria.class4_tax_rate),
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
        "phase_in_note": _phase_in_note(phase),
        "variance": {
            "subject_sf": cs.subject.get("sf"),
            "subject_emv": cs.subject.get("curmkttot"),
            "subject_bldg_class": cs.subject.get("bldg_class"),
            "stories_column": True,                  # STEP A gate passed (NumFloors 99.83% fill)
            "views": [
                {"name": v.name, "dimension": v.dimension,
                 "rows": [_variance_row(d, cs.subject) for d in v.rows]}
                for v in (var.views["nearest_by_distance"],
                          var.views["nearest_by_sf"],
                          var.views["most_different_by_assessed"])
            ],
            "all_diffs": [_variance_row(d, cs.subject) for d in var.all_diffs],
        },
        "provenance": stats.provenance,
        "context": CONTEXT,
        "rung3": {"enabled": False, "section": "Calculate Implied Cap Rate With User-Provided NOI"},
        "expense_ratio": _expense_section(juris, criteria, cs.subject),
        "radius_control": _radius_control(radius_selection),
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
