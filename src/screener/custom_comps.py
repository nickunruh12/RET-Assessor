"""Custom-comps screening — the manual-override lane (contract: docs/api_contracts/custom_comps.md).

The user supplies a subject BBL and their OWN list of comparable BBLs; the tool runs its existing
stats / variance / provenance machinery on that exact set instead of auto-selecting. It does NOT
vet the user's comp selection — that is the whole point, and it is disclosed as an explicit field.

NEW PATH. It reuses the engine wholesale (CompRow / CompSet, compute_stats, compute_variance,
build_screen_view, citations, land-dominant + per-SF suppression) but BYPASSES select_comps. The
auto-selection engine is untouched: office / retail / industrial `/api/screen` output is
byte-identical. The one genuinely new mechanism is `select_from_bbls` — building a CompSet directly
from user-given BBLs, per-comp validation, per-comp origin tagging, and optional hybrid auto-fill.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from .abatements import icap_bbls
from .comps import (
    EARTH_RADIUS_MI,
    CompRow,
    CompSet,
    _rows_to_dicts,
    select_comps,
)
from .industrial_comps import coverage_ratio, select_industrial_comps
from .jurisdiction import CompCriteria, Jurisdiction
from .retail_comps import select_retail_comps
from .schema import Citation
from .taxable_series import taxable_series

CONTRACT_VERSION = "1.0.0"
MIN_VALID_COMPS = 2                 # below this we refuse (a distribution needs >= 2 points)
MIN_COMP_COUNT = 8                  # the auto-engine's minimum; below it we flag / offer auto-fill
LAND_DOMINANT_THR = 0.30           # matches industrial coverage_exclusion_threshold

NOT_VETTED_STAMP = (
    "Comparables are user-provided and were NOT screened by the tool's selection logic: no size "
    "band, distance cap, building-class match, or minimum-count enforcement was applied. The "
    "statistics describe this exact set as given.")
RELIABILITY_NOTE = "Distribution statistics are less reliable below the 8-comp minimum."

# Origin tags — the core per-comp integrity field.
USER = "user-supplied"
TOOL = "tool-selected"

ORIGIN_STAMP = {
    USER: "User-supplied comp; not vetted by the tool's selection safeguards.",
    TOOL: "Tool-selected to reach the 8-comp minimum, matched to the subject.",
}


# --------------------------------------------------------------------------- #
def _asset_type(bldg_class: str | None) -> str:
    c = bldg_class or ""
    if c.startswith("O"):
        return "office"
    if c.startswith("K"):
        return "retail"
    if c.startswith("F"):
        return "industrial"
    return "other"


def _haversine(lat1, lon1, lat2, lon2) -> float:
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return EARTH_RADIUS_MI * 2 * math.asin(math.sqrt(a))


def _pull_parcel(con, bbl: str, comp_table: str = "parcels") -> dict | None:
    rows = _rows_to_dicts(con.execute(f"SELECT * FROM {comp_table} WHERE parcel_id = ?", [bbl]))
    return rows[0] if rows else None


def _in_table(con, table: str, col: str, bbl: str, cast_int: bool = False) -> bool:
    val = f"TRY_CAST(? AS BIGINT)" if cast_int else "?"
    return con.execute(f"SELECT 1 FROM {table} WHERE {col} = {val} LIMIT 1", [bbl]).fetchone() is not None


# --------------------------------------------------------------------------- #
@dataclass
class CompValidation:
    """Per-comp resolution result — never silent."""
    bbl: str
    status: str            # "valid" | "excluded" | "not_found"
    reason: str | None     # human-readable reason for exclusion / not-found
    row: dict | None = None


def _classify_comp(con, bbl: str, subject_bbl: str) -> CompValidation:
    """Resolve and classify ONE supplied comp BBL. class-4 universe = parcels ∪ parcels_no_sf;
    all NYC lots = pluto_lots. That lets us honestly distinguish 'not class 4' from 'not found'
    without a network call (the loaded roll is class-4 only)."""
    if bbl == subject_bbl:
        return CompValidation(bbl, "excluded", "excluded: same BBL as the subject")
    row = _pull_parcel(con, bbl)
    if row is not None:
        if not (row.get("curmkttot") and row["curmkttot"] > 0):
            return CompValidation(bbl, "excluded", "excluded: non-positive market value (tax-exempt)")
        if row.get("pluto_latitude") is None or row.get("pluto_longitude") is None:
            return CompValidation(bbl, "excluded", "excluded: no coordinates on record")
        return CompValidation(bbl, "valid", None, row)
    # Not in the usable class-4 table. Distinguish the three absent cases locally.
    if _in_table(con, "parcels_no_sf", "parcel_id", bbl):
        return CompValidation(bbl, "excluded", "excluded: class 4 but no gross building area on record")
    if _in_table(con, "pluto_lots", "bbl_int", bbl, cast_int=True):
        return CompValidation(bbl, "excluded", "excluded: not tax class 4")
    return CompValidation(bbl, "not_found", "not found in the roll")


# --------------------------------------------------------------------------- #
def _subject_summary(con, juris: Jurisdiction, criteria: CompCriteria, subj: dict) -> dict:
    """Same shape select_comps builds, so build_screen_view consumes it unchanged. Plus the
    subject-side land-dominant flag (reused from the industrial path) so a land-dominant subject's
    own per-SF is withheld."""
    bbl = subj["parcel_id"]
    subj_cov = coverage_ratio(subj.get("pluto_bldgarea"), subj.get("pluto_lotarea"))
    return {
        "parcel_id": bbl,
        "bldg_class": subj.get("bldg_class"),
        "bucket": _asset_type(subj.get("bldg_class")),
        "bucket_label": f"Custom comps ({_asset_type(subj.get('bldg_class'))})",
        "borough": juris.borough_of(bbl),
        "zip_code": subj.get("zip_code"),
        "sf": subj.get("sf"),
        "sf_source": subj.get("sf_source"),
        "year_built": subj.get("year_built"),
        "house_number": subj.get("house_number"),
        "street_name": subj.get("street_name"),
        "pluto_address": subj.get("pluto_address"),
        "stories": subj.get("pluto_numfloors"),
        "latitude": subj.get("pluto_latitude"),
        "longitude": subj.get("pluto_longitude"),
        "curmkttot": subj.get("curmkttot"),
        "curtxbtot": subj.get("curtxbtot"),
        "curtrntot": subj.get("curtrntot"),
        "curacttot": subj.get("curacttot"),
        "pytrntot": subj.get("pytrntot"),
        "roll_year": subj.get("roll_year"),
        "has_icap": bool(icap_bbls(con, [bbl])),
        "taxable_series": taxable_series(con, bbl),
        "subject_land_dominant": bool(subj_cov is not None and subj_cov < LAND_DOMINANT_THR),
    }


def _comprow_from_parcel(c: dict, subj: dict, subject_class: str | None) -> CompRow:
    """Build a CompRow from a class-4 parcel row, distance measured from the subject. land_dominant
    reuses the industrial coverage rule so the shared per-SF exclusion fires automatically."""
    rd = c["retrieval_date"]
    cov = coverage_ratio(c.get("pluto_bldgarea"), c.get("pluto_lotarea"))
    citation = Citation(
        source_dataset=c["source_dataset"], dataset_version=c["dataset_version"],
        roll_year=c["roll_year"],
        retrieval_date=rd if isinstance(rd, date) else date.fromisoformat(str(rd)),
        parcel_id=c["parcel_id"],
    )
    return CompRow(
        citation=citation,
        bldg_class=c.get("bldg_class"),
        bucket=_asset_type(c.get("bldg_class")),
        # 'exact' means shares the subject's building class; 'adjacent' otherwise. For custom comps
        # this is informational only (no selection safeguard rode on it).
        match_type="exact" if c.get("bldg_class") == subject_class else "adjacent",
        sf=c["sf"],
        sf_source=c["sf_source"],
        sf_dataset_version=c.get("pluto_dataset_version"),
        year_built=c.get("year_built"),
        house_number=c.get("house_number"),
        street_name=c.get("street_name"),
        pluto_address=c.get("pluto_address"),
        stories=c.get("pluto_numfloors"),
        distance_miles=round(_haversine(subj["pluto_latitude"], subj["pluto_longitude"],
                                        c["pluto_latitude"], c["pluto_longitude"]), 4),
        latitude=c["pluto_latitude"],
        longitude=c["pluto_longitude"],
        curmkttot=c.get("curmkttot"),
        curtxbtot=c.get("curtxbtot"),
        curtrntot=c.get("curtrntot"),
        curacttot=c.get("curacttot"),
        land_dominant=bool(cov is not None and cov < LAND_DOMINANT_THR),
    )


def _autofill_comps(con, criteria, juris, subject_bbl, subject_class, have: set, need: int) -> list[CompRow]:
    """Fill up to `need` slots with the tool's NORMAL subject-based selection for the subject's
    asset type. Matches the SUBJECT, never the user's picks. Reuses the auto-selectors' own
    CompRows (already distance/land-dominant computed vs the subject)."""
    atype = _asset_type(subject_class)
    if atype == "office":
        cs_auto = select_comps(con, subject_bbl, juris, criteria)
    elif atype == "retail":
        cs_auto, _ = select_retail_comps(con, subject_bbl, juris, criteria)
    elif atype == "industrial":
        cs_auto, _ = select_industrial_comps(con, subject_bbl, juris, criteria)
    else:
        return []                       # no auto engine for this asset class
    if cs_auto.refused:
        return []
    picks: list[CompRow] = []
    for c in cs_auto.comps:
        pid = c.citation.parcel_id
        if pid in have or pid == subject_bbl:
            continue
        picks.append(c)
        if len(picks) >= need:
            break
    return picks


# --------------------------------------------------------------------------- #
@dataclass
class CustomMeta:
    entered_count: int
    valid_count: int
    validation: list[CompValidation]
    origins: dict = field(default_factory=dict)     # parcel_id -> USER | TOOL
    autofilled: int = 0
    autofill_available: bool = False
    fill_mode: str = "none"                          # "none" | "autofill"
    refused: bool = False
    refuse_reason: str | None = None
    refuse_message: str | None = None
    subject: dict | None = None


def select_from_bbls(con, subject_bbl: str, comp_bbls: list[str], criteria: CompCriteria,
                     juris: Jurisdiction, *, fill: str = "none") -> tuple[CompSet, CustomMeta]:
    """Build a CompSet from user-given BBLs (no auto-selection), with per-comp validation, origin
    tagging, and optional hybrid auto-fill to the 8-comp minimum."""
    # --- subject validation ---
    subj = _pull_parcel(con, subject_bbl)
    if subj is None:
        reason = ("not_class_4" if _in_table(con, "pluto_lots", "bbl_int", subject_bbl, cast_int=True)
                  else "subject_not_found")
        msg = ("Subject is not tax class 4 (this tool screens class 4 only)."
               if reason == "not_class_4" else "No parcel found for the subject BBL.")
        return (CompSet(subject_bbl, None, [], 0, None, True, {}, note=reason),
                CustomMeta(0, 0, [], refused=True, refuse_reason=reason, refuse_message=msg))
    if not (subj.get("curmkttot") and subj["curmkttot"] > 0):
        return (CompSet(subject_bbl, None, [], 0, None, True, {}, note="subject_tax_exempt"),
                CustomMeta(0, 0, [], refused=True, refuse_reason="subject_tax_exempt",
                           refuse_message="Subject is tax-exempt (no positive market value); nothing to compare."))
    if subj.get("pluto_latitude") is None or subj.get("pluto_longitude") is None:
        return (CompSet(subject_bbl, None, [], 0, None, True, {}, note="subject_no_coordinates"),
                CustomMeta(0, 0, [], refused=True, refuse_reason="subject_no_coordinates",
                           refuse_message="Subject has no coordinates on record; distances can't be computed."))

    subject_class = subj.get("bldg_class")
    subject_summary = _subject_summary(con, juris, criteria, subj)

    # --- per-comp validation (dedup, drop the subject) ---
    seen: set[str] = set()
    ordered: list[str] = []
    for b in comp_bbls:
        b = (b or "").strip()
        if b and b not in seen:
            seen.add(b)
            ordered.append(b)
    validation = [_classify_comp(con, b, subject_bbl) for b in ordered]
    valid = [v for v in validation if v.status == "valid"]
    valid_count = len(valid)

    atype = _asset_type(subject_class)
    autofill_available = atype in ("office", "retail", "industrial")

    # --- refuse only on the true floor (never on the 8-count) ---
    if valid_count < MIN_VALID_COMPS:
        return (CompSet(subject_bbl, subject_summary, [], 0, None, True, {}, note="insufficient_valid_comps"),
                CustomMeta(len(ordered), valid_count, validation, autofill_available=autofill_available,
                           fill_mode=fill, refused=True, refuse_reason="insufficient_valid_comps",
                           refuse_message=(f"Only {valid_count} valid class-4 comp(s) after validation; "
                                           f"at least {MIN_VALID_COMPS} are needed to form a distribution."),
                           subject=subject_summary))

    # --- build user comps ---
    user_rows = [_comprow_from_parcel(v.row, subj, subject_class) for v in valid]
    origins = {r.citation.parcel_id: USER for r in user_rows}
    comps = list(user_rows)

    # --- optional hybrid auto-fill to the 8-comp minimum (subject-matched, tagged tool-selected) ---
    autofilled = 0
    if fill == "autofill" and valid_count < MIN_COMP_COUNT and autofill_available:
        have = set(origins)
        picks = _autofill_comps(con, criteria, juris, subject_bbl, subject_class,
                                have, MIN_COMP_COUNT - valid_count)
        for c in picks:
            origins[c.citation.parcel_id] = TOOL
        comps += picks
        autofilled = len(picks)

    # ICAP disclosure tag (one lookup for the set) — same as the auto path.
    icap = icap_bbls(con, [c.citation.parcel_id for c in comps])
    for c in comps:
        c.has_icap = c.citation.parcel_id in icap

    radius_used = round(max((c.distance_miles for c in comps), default=0.0), 4)
    cs = CompSet(
        subject_bbl, subject_summary, comps, len(comps), radius_used, False,
        criteria={"basis": "user_provided", "selection_safeguards_applied": False},
        candidates_within_cap=len(comps),
        sf_band_applied=False, sf_band_relaxed=False, fallback_triggered=False,
        exact_count=sum(1 for c in comps if c.match_type == "exact"),
        adjacent_count=sum(1 for c in comps if c.match_type == "adjacent"),
    )
    meta = CustomMeta(len(ordered), valid_count, validation, origins=origins,
                      autofilled=autofilled, autofill_available=autofill_available,
                      fill_mode=fill, subject=subject_summary)
    return cs, meta


# --------------------------------------------------------------------------- #
def _validation_report(meta: CustomMeta) -> dict:
    """The per-comp resolution report — every entered BBL accounted for, never silent."""
    return {
        "entered_count": meta.entered_count,
        "valid_count": meta.valid_count,
        "excluded": [{"bbl": v.bbl, "reason": v.reason}
                     for v in meta.validation if v.status == "excluded"],
        "not_found": [{"bbl": v.bbl, "reason": v.reason}
                      for v in meta.validation if v.status == "not_found"],
    }


def build_custom_screen_view(con, criteria: CompCriteria, juris: Jurisdiction, *,
                             subject_bbl: str, comp_bbls: list[str], fill: str = "none") -> dict:
    """Assemble the custom-comps screen: build a CompSet from the user's BBLs, run the SHARED
    stats/variance/serialize machinery on it, then stamp origin + the not-vetted flag + options.
    Reuses build_screen_view wholesale; adds only custom-specific fields."""
    from .serialize import DISCLAIMER, build_screen_view   # local import avoids a cycle

    cs, meta = select_from_bbls(con, subject_bbl, comp_bbls, criteria, juris, fill=fill)

    # --- refusal: still return the validation report + the not-vetted flag ---
    if cs.refused:
        subj = meta.subject
        return {
            "status": "refused",
            "product": "custom_comps",
            "contract_version": CONTRACT_VERSION,
            "reason": meta.refuse_reason,
            "message": meta.refuse_message,
            "disclaimer": DISCLAIMER,
            "subject": ({"bbl": subj["parcel_id"], "bldg_class": subj.get("bldg_class"),
                         "borough": subj.get("borough")} if subj else {"bbl": subject_bbl}),
            "user_comps_not_vetted": True,
            "comp_source": {"type": "user_provided", "selection_safeguards_applied": False,
                            **_validation_report(meta)},
        }

    # --- reuse the full auto-screen assembly (stats / variance / signals / provenance) ---
    base = build_screen_view(con, criteria, juris, bbl=subject_bbl, comp_set=cs,
                             suppress_per_sf=not cs.subject.get("sf"))

    origins = meta.origins
    subject_type = _asset_type(cs.subject.get("bldg_class"))
    below_min = meta.valid_count < MIN_COMP_COUNT

    # --- top-level product identity + the unmissable not-vetted flag ---
    base["product"] = "custom_comps"
    base["contract_version"] = CONTRACT_VERSION
    base["user_comps_not_vetted"] = True
    base["selection_safeguards_applied"] = False

    # --- comp_source block (validation report + safeguards flag + stamp) ---
    comp_mix = None
    if meta.autofilled:
        comp_mix = (f"{cs.count} comps: {meta.valid_count} user-supplied (not vetted by selection "
                    f"logic), {meta.autofilled} tool-selected to reach the {MIN_COMP_COUNT}-comp minimum.")
    elif below_min:
        comp_mix = (f"{meta.valid_count} user-supplied comps (not vetted by selection logic); "
                    f"below the {MIN_COMP_COUNT}-comp minimum — {RELIABILITY_NOTE.lower()}")
    base["comp_source"] = {
        "type": "user_provided",
        "selection_safeguards_applied": False,
        "stamp": NOT_VETTED_STAMP,
        **_validation_report(meta),
        "user_supplied_count": meta.valid_count,
        "tool_selected_count": meta.autofilled,
        "screened_count": cs.count,
        "distance_miles_max": cs.radius_used_miles,     # FYI only — NOT a cap, NOT a filter
        "comp_mix": comp_mix,
    }
    base["thin_set"] = bool(below_min and not meta.autofilled)

    # --- options block: expose BOTH choices when below the 8-comp minimum ---
    base["options"] = (None if not below_min else {
        "valid_comp_count": meta.valid_count,
        "below_min": True,
        "min_comp_count": MIN_COMP_COUNT,
        "reliability_note": RELIABILITY_NOTE,
        "choices": {
            "thin_run": {
                "available": True,
                "description": (f"Screen the {meta.valid_count} user-supplied comps as-is "
                                f"(flagged as a thin set; percentiles less reliable)."),
            },
            "autofill": {
                "available": meta.autofill_available,
                "description": (f"Auto-fill {MIN_COMP_COUNT - meta.valid_count} tool-selected comps, "
                                f"matched to the subject (same asset type, size band, and distance "
                                f"criteria the auto-engine uses), to reach {MIN_COMP_COUNT}."),
                "unavailable_reason": (None if meta.autofill_available
                                       else "no auto-selection engine for this asset class"),
            },
        },
    })

    # --- per-comp origin: inject onto every comp the response exposes ---
    for view in base.get("variance", {}).get("views", []):
        for r in view.get("rows", []):
            o = origins.get(r.get("parcel_id"))
            r["origin"] = o
            r["origin_note"] = ORIGIN_STAMP.get(o)
    for r in base.get("variance", {}).get("all_diffs", []):
        r["origin"] = origins.get(r.get("parcel_id"))
    for sig in base.get("signals", []):
        for p in (sig.get("comp_points") or []):
            p["origin"] = origins.get(p.get("bbl"))

    # --- top-level comps[] summary carrying the integrity tags ---
    base["comps"] = [{
        "bbl": c.citation.parcel_id,
        "origin": origins.get(c.citation.parcel_id),
        "bldg_class": c.bldg_class,
        "asset_type": c.bucket,
        "cross_type": c.bucket != subject_type,
        "land_dominant": c.land_dominant,
        "distance_miles": c.distance_miles,
        "vetted_by_selection_logic": origins.get(c.citation.parcel_id) == TOOL,
    } for c in cs.comps]

    # --- comp_meta: mark the basis so no selection chrome is inferred ---
    if isinstance(base.get("comp_meta"), dict):
        base["comp_meta"]["basis"] = "user_provided"
        base["comp_meta"]["selection_safeguards_applied"] = False

    return base
