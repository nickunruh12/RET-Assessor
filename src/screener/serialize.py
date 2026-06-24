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
    "heading": "Context (background only — not a verdict, not advice)",
    "items": [
        {"label": "How class-4 is valued",
         "text": "NYC DOF values class-4 (commercial) property primarily by income "
                 "(capitalized net operating income), not by price per square foot. This "
                 "screen compares published figures across nearby peers; it does not "
                 "reproduce the assessor's method.",
         "source": "NYC DOF — Determining Your Assessed Value",
         "url": "https://www.nyc.gov/site/finance/property/property-determining-your-assessed-value.page"},
        {"label": "Class-4 assessment ratio",
         "text": "Assessed value is set at 45% of market value for class 4.",
         "source": "NYC DOF — Determining Your Assessed Value",
         "url": "https://www.nyc.gov/site/finance/property/property-determining-your-assessed-value.page"},
        {"label": "FY2026 class-4 tax rate",
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


def _f(x, nd=2):
    return None if x is None else round(float(x), nd)


def _subject_panel(subject: dict | None, resolve: ResolveResult | None) -> dict | None:
    if subject is None:
        return None
    addr = None
    if resolve is not None:
        bits = [resolve.house_number, resolve.street]
        loc = resolve.borough or (f"ZIP {resolve.zip_code}" if resolve.zip_code else None)
        addr = ", ".join([b for b in [" ".join(x for x in bits if x), loc] if b]) or None
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


def _variance_row(d) -> dict:
    return {
        "parcel_id": d.citation.parcel_id, "bldg_class": d.bldg_class,
        "match_type": d.match_type, "differs_on": d.differs_on,
        "assessed_pct_diff": d.assessed_pct_diff, "sf_pct_diff": d.sf_pct_diff,
        "distance_miles": d.distance_miles, "year_built": d.year_built,
        "year_built_missing": d.year_built_missing,
        "citation": d.citation.model_dump(mode="json"),
        "sf_dataset_version": d.sf_dataset_version,
    }


def _refused(stage, reason, message, *, subject=None, resolve=None, extra=None) -> dict:
    out = {
        "status": "refused", "stage": stage, "reason": reason, "message": message,
        "disclaimer": DISCLAIMER, "context": CONTEXT,
        "subject": _subject_panel(subject, resolve),
        "rung3": {"enabled": False, "section": "RUNG 3 (user-supplied, off by default)"},
    }
    if extra:
        out.update(extra)
    return out


def build_screen_view(con: duckdb.DuckDBPyConnection, criteria: CompCriteria,
                      juris: Jurisdiction, *, bbl: str | None = None,
                      resolve: ResolveResult | None = None) -> dict:
    """Assemble the full page view model from a BBL (or a prior address resolution)."""
    # Address resolution refusal (out-of-scope, tax-exempt, address not found, …).
    if resolve is not None and not resolve.ok:
        return _refused("resolve", resolve.reason, resolve.message, resolve=resolve,
                        subject=None)
    subject_bbl = (resolve.bbl if resolve is not None else bbl)
    if not subject_bbl:
        return _refused("resolve", "missing_inputs", RESOLVER_MESSAGES["missing_inputs"])

    cs = select_comps(con, subject_bbl, juris, criteria)
    if cs.refused:
        msg = refusal_message(cs.note) or REFUSAL_MESSAGES.get(cs.note) or cs.note
        return _refused("comps", cs.note, msg, subject=cs.subject, resolve=resolve,
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
        "subject": _subject_panel(cs.subject, resolve),
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
        "phase_in_gap": {
            "label": phase.label, "subject_value": _f(phase.subject_value, 4),
            "median": _f(phase.median, 4), "n": phase.n, "excluded_blank": phase.excluded_blank,
            "descriptive": True,
        },
        "variance": {
            "views": [
                {"name": v.name, "dimension": v.dimension,
                 "rows": [_variance_row(d) for d in v.rows]}
                for v in (var.views["nearest_by_distance"],
                          var.views["nearest_by_sf"],
                          var.views["most_different_by_assessed"])
            ],
            "all_diffs": [_variance_row(d) for d in var.all_diffs],
        },
        "provenance": stats.provenance,
        "context": CONTEXT,
        "rung3": {"enabled": False, "section": "RUNG 3 (user-supplied, off by default)"},
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
