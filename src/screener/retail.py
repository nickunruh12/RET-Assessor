"""Retail (K-code) classifier — Stage 1 of retail expansion.

Classifies a class-4 RETAIL parcel by MEASURED PLUTO floor-area share, NOT by K-code
(diagnosis: PLUTO `retailarea` is 98% filled and ~99% reconciled, so the use-mix is
measurable rather than inferred from the coarse K-code). This module is the classifier
ONLY — it pulls no comps and is not wired into the live screen yet; office remains the only
user-screenable type. No LLM, no verdicts: it labels a parcel and states a provenance fact.

Inputs: the parcel's K building-class code + PLUTO area fields (bldgarea, retailarea,
officearea, resarea). Output: (category, per_sf_shown, disclosure_note) + PLUTO provenance.

Classification (exact):
  Step 1 — specialized format by K-code: K3/K5/K6/K7/K8/K9 -> that format's category. Their
           comp strategies come in a later stage; here we only label them.
  Step 2 — core (K1/K2/K4) by retail_share = retailarea / bldgarea:
             retail_share >= pure_threshold        -> pure_retail
             else (mixed), second use in ORDER (office precedence):
               officearea/bldgarea >= second_use_threshold -> retail_office
               resarea/bldgarea   >= second_use_threshold -> retail_residential
               else                                        -> retail_other

Per-SF gating is UNIVERSAL and by retail_share ALONE (independent of category): a parcel
shows per-SF only when retail_share >= pure_threshold. A specialized parcel whose retail
share is low (e.g. a ground-floor bank branch in a tower) correctly gets per_sf_shown=False.

Edge case — retail_share not measurable (retailarea missing or bldgarea<=0): NEVER guess
pure. Default to retail_other (mixed treatment), per_sf_shown=False, with a "could not be
measured" note. (Specialized formats keep their K-code category but still get per_sf=False.)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import config
from .jurisdiction import CompCriteria

# Category constants -------------------------------------------------------------------
PURE_RETAIL = "pure_retail"
RETAIL_OFFICE = "retail_office"
RETAIL_RESIDENTIAL = "retail_residential"
RETAIL_OTHER = "retail_other"

# Specialized formats: category is the K-code's format (labelled, not share-classified).
SPECIALIZED = {
    "K3": "K3_department", "K5": "K5_food", "K6": "K6_center",
    "K7": "K7_bank", "K8": "K8_bigbox", "K9": "K9_misc",
}
CORE_CODES = {"K1", "K2", "K4"}

# Human-readable class labels used inside disclosure notes.
_LABELS = {
    PURE_RETAIL: "pure retail", RETAIL_OFFICE: "retail + office",
    RETAIL_RESIDENTIAL: "retail + residential", RETAIL_OTHER: "retail + other use",
}

_MEASURE_NOTE = ("Floor-area use-mix could not be measured for this parcel; screened "
                 "conservatively as mixed-use.")

# Thresholds are NAMED CONFIG (CompCriteria / comp_criteria.json), tunable per-metro.
_DEFAULTS: tuple[float, float] | None = None


def _default_thresholds() -> tuple[float, float]:
    global _DEFAULTS
    if _DEFAULTS is None:
        c = CompCriteria.load()
        _DEFAULTS = (c.retail_share_pure_threshold, c.mixed_use_second_use_threshold)
    return _DEFAULTS


@dataclass(frozen=True)
class RetailClassification:
    """A parcel's retail classification. `retail_share` is a PLUTO-derived figure; its
    provenance (PLUTO dataset + version) travels on `provenance`, the same discipline as the
    gross-SF figure (which also cites its PLUTO version rather than the roll)."""

    k_code: str
    category: str
    retail_share: float | None          # retailarea / bldgarea (PLUTO); None if unmeasurable
    per_sf_shown: bool                   # gated by retail_share ALONE, not category
    note: str | None                     # disclosure note (None when code agrees with route)
    provenance: dict = field(default_factory=dict)


def _classification_note(k_code: str, category: str) -> str | None:
    """Fire ONLY when the K-code's plain meaning disagrees with the measured route."""
    if k_code == "K4" and category == PURE_RETAIL:
        return ("Coded K4 (mixed-use) but >=80% retail by floor area; screened as pure "
                "retail.")
    if k_code == "K2" and category != PURE_RETAIL:
        return (f"Coded K2 (multi-store retail) but carries significant non-retail floor "
                f"area; screened as {_LABELS[category]} by measured use-mix.")
    if k_code == "K4" and category != PURE_RETAIL:
        return (f"Coded K4 (predominant retail with other uses); screened as "
                f"{_LABELS[category]} by measured use-mix.")
    return None


def classify_retail(k_code: str | None, bldgarea, retailarea, officearea, resarea, *,
                    pure_threshold: float | None = None,
                    second_use_threshold: float | None = None,
                    pluto_version: str | None = None) -> RetailClassification:
    """Classify one retail (K) parcel from its K-code + PLUTO floor areas. Pure function:
    no DB, no comps, no network."""
    if pure_threshold is None or second_use_threshold is None:
        dp, ds = _default_thresholds()
        pure_threshold = dp if pure_threshold is None else pure_threshold
        second_use_threshold = ds if second_use_threshold is None else second_use_threshold

    code = (k_code or "").strip().upper()
    prov = {
        "source_dataset": config.PLUTO_DATASET,
        "dataset_version": pluto_version,
        "derived": "retail_share = retailarea / bldgarea (PLUTO floor areas)",
    }

    # retail_share — PLUTO-measured; None when unmeasurable (NEVER inferred as pure).
    share = (retailarea / bldgarea) if (retailarea is not None and bldgarea and bldgarea > 0) else None
    per_sf = share is not None and share >= pure_threshold
    share_out = round(share, 4) if share is not None else None

    # Step 1 — specialized format: category is the K-code format; per-SF still by share alone;
    # no classification note in this stage (their fallback notes come later).
    if code in SPECIALIZED:
        return RetailClassification(code, SPECIALIZED[code], share_out, per_sf, None, prov)

    # Step 2 — core (K1/K2/K4). Unmeasurable -> conservative mixed, never pure.
    if share is None:
        return RetailClassification(code, RETAIL_OTHER, None, False, _MEASURE_NOTE, prov)

    if share >= pure_threshold:
        category = PURE_RETAIL
    else:
        off_share = (officearea / bldgarea) if officearea is not None else 0.0
        res_share = (resarea / bldgarea) if resarea is not None else 0.0
        if off_share >= second_use_threshold:           # office precedence
            category = RETAIL_OFFICE
        elif res_share >= second_use_threshold:
            category = RETAIL_RESIDENTIAL
        else:
            category = RETAIL_OTHER

    return RetailClassification(code, category, share_out, per_sf,
                                _classification_note(code, category), prov)
