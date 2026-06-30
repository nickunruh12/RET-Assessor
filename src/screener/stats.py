"""Statistics layer — deterministic distribution functions over a comp set.

Pure functions. No LLM, no randomness, no I/O. Given a CompSet, compute, PER SIGNAL,
the distribution (mean, median, min, max, population stddev) and the subject's
percentile, on the correct population for that signal.

The three non-negotiable correctness rules (KNOWN_LIMITS.md):
  1. Blanks are EXCLUDED from each stat and COUNTED — never zeroed. Every signal
     reports how many comps were excluded for missing its field.
  2. The subject is NEVER in its own distribution or percentile. (The comp set already
     excludes the subject; the subject's value is used only to place its percentile.)
  3. Every distribution carries its `n` so confidence is visible.

Provenance: the citation tuple (carried on every CompRow) and the exact-vs-adjacent
composition flow through to the result, so each distribution stays traceable to its comps.

Signals:
  - assessed_value_market : curmkttot, all comps.
  - tax_bill              : curtxbtot * FY2026 class-4 rate, all comps.
  - mv_per_gross_sf       : curmkttot / gross SF, comps with usable gross SF only;
                            REFUSES (per-signal) when the SUBJECT has no gross SF.
  - phase_in_gap          : (curacttot - curtrntot) / curacttot, descriptive.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .comps import CompSet
from .jurisdiction import CompCriteria

# Subject percentile definition, stated so it is hand-verifiable:
PERCENTILE_BASIS = "share of comps strictly below the subject's value, x100 (0 = subject is the lowest)"

# Per-SF percentile is computed on SIZE-COMPARABLE (in-band) comps only — a relaxed band can
# pack the pool with tiny, high-per-SF retail that mechanically drags the rank. Below this many
# in-band comps the percentile NUMBER is suppressed (chart + distribution stay shown).
MIN_INBAND_FOR_PER_SF_PERCENTILE = 5


@dataclass
class SignalStats:
    key: str
    label: str
    unit: str
    population: str            # which comps this signal is computed on
    n: int                     # comps the stat was computed on (rule 3)
    excluded_blank: int        # comps dropped for missing this field (rule 1)
    mean: float | None
    median: float | None
    minimum: float | None
    maximum: float | None
    stddev: float | None       # population standard deviation (the comp set is the population)
    subject_value: float | None
    subject_percentile: float | None
    percentile_basis: str = PERCENTILE_BASIS
    refused: bool = False
    refusal_reason: str | None = None
    notes: list[str] = field(default_factory=list)
    # Per-SF only: the subset size the percentile was actually computed on (in-band comps), and
    # a stated reason whenever it differs from the chart n or the number is suppressed (None =
    # percentile computed on the full chart population, no disclosure needed).
    percentile_n: int | None = None
    percentile_note: str | None = None


@dataclass
class StatsResult:
    subject_bbl: str
    subject: dict | None
    refused: bool                       # whole-comp-set refusal (out_of_scope / insufficient / ...)
    note: str | None
    radius_used_miles: float | None
    comp_count: int
    sf_band_applied: bool
    composition: dict                   # exact_count / adjacent_count / adjacent_breakdown / fallback_triggered
    low_exact_caution: bool
    caution_message: str | None
    provenance: dict
    signals: dict[str, SignalStats] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
def _percentile_rank(values: list[float], subject_value: float | None) -> float | None:
    """Subject's percentile = 100 * (# comps strictly below) / n. None if no subject value."""
    if subject_value is None or not values:
        return None
    below = sum(1 for v in values if v < subject_value)
    return round(100.0 * below / len(values), 2)


def _describe(values: list[float]) -> dict:
    if not values:
        return dict(mean=None, median=None, minimum=None, maximum=None, stddev=None)
    return dict(
        mean=statistics.fmean(values),
        median=statistics.median(values),
        minimum=min(values),
        maximum=max(values),
        stddev=statistics.pstdev(values) if len(values) > 1 else 0.0,
    )


def _signal_from_pairs(
    key: str, label: str, unit: str, population: str,
    comp_values: list[float | None], subject_value: float | None,
) -> SignalStats:
    """Build a SignalStats from per-comp values (None = blank, excluded + counted)."""
    present = [v for v in comp_values if v is not None]
    excluded = sum(1 for v in comp_values if v is None)
    d = _describe(present)
    refused = len(present) == 0
    return SignalStats(
        key=key, label=label, unit=unit, population=population,
        n=len(present), excluded_blank=excluded,
        mean=d["mean"], median=d["median"], minimum=d["minimum"],
        maximum=d["maximum"], stddev=d["stddev"],
        subject_value=subject_value,
        subject_percentile=_percentile_rank(present, subject_value),
        refused=refused,
        refusal_reason="no_comp_values_present" if refused else None,
    )


# --------------------------------------------------------------------------- #
def compute_stats(cs: CompSet, criteria: CompCriteria, *, suppress_per_sf: bool = False,
                  per_sf_note: str | None = None) -> StatsResult:
    """Compute every signal's distribution + the subject's percentile for a comp set.

    `suppress_per_sf` (retail mixed-use): the subject HAS gross SF, but per-SF is suppressed
    because the floor area blends uses, so the $/SF distribution would not be comparable. It
    reuses the SAME per-signal refusal path as the office no-SF case — the only office-visible
    default is False (office behaviour is unchanged)."""
    subj = cs.subject

    if cs.refused or not cs.comps:
        return StatsResult(
            subject_bbl=cs.subject_bbl, subject=subj, refused=True, note=cs.note,
            radius_used_miles=cs.radius_used_miles, comp_count=cs.count,
            sf_band_applied=cs.sf_band_applied,
            composition={}, low_exact_caution=False, caution_message=None,
            provenance={}, signals={},
        )

    comps = cs.comps
    rate = criteria.class4_tax_rate

    # provenance — uniform roll tuple across comps + PLUTO version(s) for the SF source
    c0 = comps[0].citation
    pluto_versions = sorted({c.sf_dataset_version for c in comps if c.sf_dataset_version})
    provenance = {
        "source_dataset": c0.source_dataset,
        "dataset_version": c0.dataset_version,
        "roll_year": c0.roll_year,
        "retrieval_date": c0.retrieval_date.isoformat(),
        "sf_pluto_versions": pluto_versions,
        "tax_rate_applied": rate,
        "percentile_basis": PERCENTILE_BASIS,
        # Raw source columns behind each chart (titles drop these for readability;
        # kept here so every figure still traces to its exact roll field).
        "signal_fields": {
            "Estimated Market Value According to DOF": "curmkttot",
            "Tax Bill (10.848% Class-4 Rate)": "curtxbtot x 0.10848",
            "Real Estate Taxes (subject)": "curtxbtot x 0.10848",
            "DOF Market Value Per Gross Building Area": "curmkttot / gross building area",
            "Phase-in gap": "(curacttot - curtrntot) / curacttot",
        },
    }

    signals: dict[str, SignalStats] = {}

    # 1. Estimated market value — all comps. (Matches DOF's public "Estimated Market
    #    Value" line; the underlying field is curmkttot — see provenance.)
    signals["assessed_value_market"] = _signal_from_pairs(
        "assessed_value_market", "Estimated Market Value According to DOF",
        "$", "all comps", [c.curmkttot for c in comps], subj.get("curmkttot"),
    )

    # 2. Tax bill — all comps; transitional taxable x FY2026 class-4 rate.
    signals["tax_bill"] = _signal_from_pairs(
        "tax_bill", "Tax Bill (10.848% Class-4 Rate)", "$ (tax)", "all comps",
        [c.curtxbtot * rate if c.curtxbtot is not None else None for c in comps],
        subj.get("curtxbtot") * rate if subj.get("curtxbtot") is not None else None,
    )

    # 3. Market value per gross building area — comps with usable gross SF only.
    #    Per-signal REFUSAL when the SUBJECT has no gross SF (locked $/SF contract).
    if not subj.get("sf") or suppress_per_sf:
        if suppress_per_sf and subj.get("sf"):
            reason = "per_sf_suppressed_mixed_use"
            note = per_sf_note or ("Per-SF not shown: building's floor area blends retail with "
                                   "other uses. Assessed-value and tax-bill distributions are "
                                   "unaffected.")
        else:
            reason = "subject_no_gross_building_area"
            note = ("Market-value-per-SF unavailable, gross building area missing for this "
                    "parcel. Assessed-value and tax-bill distributions are unaffected.")
        signals["mv_per_gross_sf"] = SignalStats(
            key="mv_per_gross_sf",
            label="Market value per gross building area (curmkttot / gross SF)",
            unit="$/gross_sf", population="comps with usable gross building area",
            n=0, excluded_blank=sum(1 for c in comps if not c.sf or c.curmkttot is None),
            mean=None, median=None, minimum=None, maximum=None, stddev=None,
            subject_value=None, subject_percentile=None,
            refused=True, refusal_reason=reason, notes=[note],
        )
    else:
        comp_psf = [
            (c.curmkttot / c.sf) if (c.sf and c.curmkttot is not None) else None
            for c in comps
        ]
        subj_psf = subj["curmkttot"] / subj["sf"] if subj.get("curmkttot") is not None else None
        sig = _signal_from_pairs(
            "mv_per_gross_sf", "DOF Market Value Per Gross Building Area",
            "$/gross_sf", "comps with usable gross building area", comp_psf, subj_psf,
        )
        sig.notes.append(f"denominator = gross building area; comp SF sources: "
                         f"{sorted({c.sf_source for c in comps})}")
        # FIX 1/2 — the per-SF PERCENTILE is computed on SIZE-COMPARABLE comps only (BldgArea
        # within ±band of the subject) WHEN the band was relaxed — a relaxed pool can pack in
        # tiny, high-per-SF retail that mechanically drags an honest-looking rank. The
        # distribution/chart/marking above are unchanged; only this rank number changes. Value
        # and tax percentiles are untouched (size doesn't corrupt them). Precedence (FIX 3):
        # this runs only when per-SF is SHOWN — a mixed-use subject is already fully refused
        # above with its own reason, so the size reason never double-prints.
        #
        # The restriction fires ONLY for K3 (always) or a band-RELAXED set. A band-held set is
        # already all-in-band, and K8 big-box is a deliberate citywide FORMAT-peer pool (no SF
        # band by design — size variation among big-box stores is expected, not contamination),
        # so both keep their full-pool percentile. Office never relaxes the band, so this whole
        # block is skipped for office (behaviour byte-identical).
        is_k3 = subj.get("retail_category") == "K3_department"
        if is_k3 or cs.sf_band_relaxed:
            band = criteria.sf_band
            subj_sf = subj.get("sf")
            inband_psf = [
                c.curmkttot / c.sf for c in comps
                if c.sf and c.curmkttot is not None
                and subj_sf * (1 - band) <= c.sf <= subj_sf * (1 + band)
            ]
            pct_basis = f"within ±{band * 100:g}% of subject gross building area"
            if is_k3:
                # FIX 2 — a department store's per-SF reads at an extreme against cross-format
                # retail; suppressed regardless of in-band count (confirmed NOT subsumed by the
                # ≥5 rule — many K3 have ample in-band comps). Chart + distribution stay shown.
                sig.subject_percentile = None
                sig.percentile_n = len(inband_psf)
                sig.percentile_note = ("Percentile not shown: a department store's per-SF sits at "
                                       "an extreme against cross-format retail, with no true "
                                       "size-and-format peers. The distribution is shown for "
                                       "context only.")
            elif len(inband_psf) >= MIN_INBAND_FOR_PER_SF_PERCENTILE:
                sig.subject_percentile = _percentile_rank(inband_psf, subj_psf)
                sig.percentile_n = len(inband_psf)
                if len(inband_psf) != sig.n:       # disclose only when it differs from the chart n
                    sig.percentile_note = (f"Percentile computed on {len(inband_psf)} "
                                           f"size-comparable comps ({pct_basis}); the chart shows "
                                           f"all {sig.n}.")
            else:
                sig.subject_percentile = None
                sig.percentile_n = len(inband_psf)
                sig.percentile_note = (f"Percentile not shown: fewer than "
                                       f"{MIN_INBAND_FOR_PER_SF_PERCENTILE} size-comparable comps "
                                       f"(only {len(inband_psf)} {pct_basis}). The distribution is "
                                       f"shown for context only.")
        signals["mv_per_gross_sf"] = sig

    # 4. Phase-in gap — descriptive: share of actual assessed not yet phased in.
    def gap(act, trn):
        return (act - trn) / act if (act and act > 0 and trn is not None) else None

    signals["phase_in_gap"] = _signal_from_pairs(
        "phase_in_gap", "Phase-in gap ((curacttot - curtrntot) / curacttot)", "fraction",
        "all comps with actual + transitional assessed",
        [gap(c.curacttot, c.curtrntot) for c in comps],
        gap(subj.get("curacttot"), subj.get("curtrntot")),
    )

    low_exact = cs.exact_count < criteria.low_exact_caution_threshold
    caution = (
        f"comp set is largely adjacent-class, interpret accordingly "
        f"({cs.exact_count} exact of {cs.count} comps)"
        if low_exact else None
    )

    return StatsResult(
        subject_bbl=cs.subject_bbl, subject=subj, refused=False, note=None,
        radius_used_miles=cs.radius_used_miles, comp_count=cs.count,
        sf_band_applied=cs.sf_band_applied,
        composition={
            "exact_count": cs.exact_count,
            "adjacent_count": cs.adjacent_count,
            "adjacent_breakdown": cs.adjacent_breakdown,
            "fallback_triggered": cs.fallback_triggered,
        },
        low_exact_caution=low_exact, caution_message=caution,
        provenance=provenance, signals=signals,
    )
