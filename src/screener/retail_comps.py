"""Retail (K) comp selection — Stage 2. Pulls same-class comps for the four CORE retail
classes and assembles the screen view, REUSING the office machinery (CompRow/CompSet,
compute_stats, compute_variance, build_screen_view) with retail's class/band/cap parameters.
It is NOT a parallel engine: selection differs (match on the MEASURED retail category from
`retail_class`, per-class radius cap, band-then-broader-retail relax cascade), but the output
is the same CompSet that the office stats/serialize path consumes.

NOT wired into the public screen — reached only via the flagged test route. Public K screens
still refuse out_of_scope_v1 (Stage 3 + adversarial pass lift that).

Relax cascade (FIXED ORDER; distance never exceeds the per-class cap):
  1. same-category, SF-banded (±50% BldgArea), swept 0.25mi -> cap
  2. relax band: same-category, ANY size, within cap
  3. broader-retail fallback: ALL FOUR core classes (specialized K3/K5/K6/K7/K8/K9 EXCLUDED),
     SF-banded first then any size, same-mix preferred (kept as 'exact'); cross-use disclosed
  4. refuse (never widen past the cap)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from . import config
from .abatements import icap_bbls
from .comps import (
    EARTH_RADIUS_MI,
    REFUSAL_MESSAGES,
    CompRow,
    CompSet,
    _radii,
    _rows_to_dicts,
)
from .jurisdiction import CompCriteria, Jurisdiction
from .schema import Citation
from .taxable_series import taxable_series

CORE_CATEGORIES = ("pure_retail", "retail_office", "retail_residential", "retail_other")
_LABELS = {"pure_retail": "Pure retail", "retail_office": "Retail + office",
           "retail_residential": "Retail + residential", "retail_other": "Retail + other use"}
_PER_SF_SUPPRESS_NOTE = ("Per-SF not shown: building's floor area blends retail with other "
                         "uses, so value-per-SF would not be comparable. Assessed-value and "
                         "tax-bill distributions are unaffected.")
_FALLBACK_NOTE = ("Fewer than 8 same-class comps nearby; comp set includes other retail "
                  "use-types (specialized formats excluded).")


@dataclass
class RetailMeta:
    category: str | None
    per_sf_shown: bool
    classification_note: str | None
    fallback_note: str | None
    per_sf_note: str | None


def _crit_summary(criteria, cap):
    return {"product": "retail", "sf_band_pct": criteria.sf_band, "radius_cap_miles": cap,
            "min_comp_count": criteria.min_comp_count, "match": "measured retail category"}


def _sweep(pool, radii, min_count, *, predicate):
    """First radius (0.25->cap) at which `predicate`-passing comps reach min_count; the comps
    within that radius. Keeps comps as local as possible, never past the cap."""
    for r in radii:
        within = [c for c in pool if c["distance_miles"] <= r + 1e-9 and predicate(c)]
        if len(within) >= min_count:
            return r, within
    return None


def _fallback_select(pool, min_count, *, same, in_band):
    """Broader-retail fallback, SAME-MIX PREFERRED. Reached only when same-category (any size)
    is < min_count within the cap, so every same-mix comp is included first; then top up with
    the NEAREST cross-use (band-eligible before off-band) just to reach the minimum — never
    over-diluting with cross-use, never past the cap (pool is already cap-bounded)."""
    same_all = [c for c in pool if same(c)]
    others = sorted((c for c in pool if not same(c)),
                    key=lambda c: (0 if in_band(c) else 1, c["distance_miles"]))
    chosen = list(same_all)
    for c in others:
        if len(chosen) >= min_count:
            break
        chosen.append(c)
    if len(chosen) < min_count:
        return None
    return round(max(c["distance_miles"] for c in chosen), 4), chosen


def select_retail_comps(con, subject_bbl: str, juris: Jurisdiction, criteria: CompCriteria,
                        comp_table: str = "parcels") -> tuple[CompSet, RetailMeta]:
    subj_rows = _rows_to_dicts(con.execute(
        f"""SELECT p.*, rc.category, rc.per_sf_shown, rc.retail_share, rc.note AS retail_note
            FROM {comp_table} p LEFT JOIN retail_class rc ON rc.parcel_id = p.parcel_id
            WHERE p.parcel_id = ?""", [subject_bbl]))
    meta = RetailMeta(None, False, None, None, None)
    if not subj_rows:
        return _refuse(subject_bbl, None, _crit_summary(criteria, None), "subject_not_found"), meta
    subj = subj_rows[0]
    category = subj.get("category")
    if category not in CORE_CATEGORIES:
        # specialized formats (Stage 3) and non-retail land here — not screenable in Stage 2.
        return _refuse(subject_bbl, None, _crit_summary(criteria, None), "out_of_scope_v1"), meta

    cap = criteria.retail_radius_caps.get(category, 1.0)
    per_sf_shown = bool(subj.get("per_sf_shown"))
    meta = RetailMeta(category, per_sf_shown, subj.get("retail_note"), None,
                      None if per_sf_shown else _PER_SF_SUPPRESS_NOTE)

    subject_summary = {
        "parcel_id": subj["parcel_id"], "bldg_class": subj.get("bldg_class"),
        "bucket": category, "bucket_label": _LABELS.get(category, category),
        "borough": juris.borough_of(subj["parcel_id"]), "zip_code": subj.get("zip_code"),
        "sf": subj.get("sf"), "sf_source": subj.get("sf_source"),
        "year_built": subj.get("year_built"), "house_number": subj.get("house_number"),
        "street_name": subj.get("street_name"), "pluto_address": subj.get("pluto_address"),
        "stories": subj.get("pluto_numfloors"),
        "latitude": subj.get("pluto_latitude"), "longitude": subj.get("pluto_longitude"),
        "curmkttot": subj.get("curmkttot"), "curtxbtot": subj.get("curtxbtot"),
        "curtrntot": subj.get("curtrntot"), "curacttot": subj.get("curacttot"),
        "pytrntot": subj.get("pytrntot"), "roll_year": subj.get("roll_year"),
        "has_icap": bool(icap_bbls(con, [subject_bbl])),
        "taxable_series": taxable_series(con, subject_bbl),
        "retail_category": category, "per_sf_shown": per_sf_shown,
    }
    crit = _crit_summary(criteria, cap)
    if criteria.exclude_non_positive_market_value and not (subj.get("curmkttot") and subj["curmkttot"] > 0):
        return _refuse(subject_bbl, subject_summary, crit, "subject_tax_exempt"), meta
    if subj.get("pluto_latitude") is None or subj.get("pluto_longitude") is None:
        return _refuse(subject_bbl, subject_summary, crit, "subject_no_coordinates"), meta

    # --- candidate pull: all CORE retail within the cap, with distance + category ---
    slat, slon = subj["pluto_latitude"], subj["pluto_longitude"]
    hav = (f"{EARTH_RADIUS_MI}*2*asin(sqrt(power(sin(radians(p.pluto_latitude-?)/2),2)+"
           f"cos(radians(?))*cos(radians(p.pluto_latitude))*power(sin(radians(p.pluto_longitude-?)/2),2)))")
    where = ["p.parcel_id != ?", "p.pluto_latitude IS NOT NULL AND p.pluto_longitude IS NOT NULL",
             "p.sf IS NOT NULL", f"rc.category IN ({','.join(['?'] * len(CORE_CATEGORIES))})"]
    params: list = [slat, slat, slon, subject_bbl, *CORE_CATEGORIES]
    condo_sql, condo_params = juris.condo_clause(criteria)
    where.append(condo_sql.replace("parcel_id", "p.parcel_id").replace("bldg_class", "p.bldg_class"))
    params += condo_params
    if criteria.exclude_non_positive_market_value:
        where.append("p.curmkttot > 0")
    sql = f"""
        SELECT p.parcel_id, p.source_dataset, p.dataset_version, p.roll_year, p.retrieval_date,
               p.bldg_class, p.zip_code, p.sf, p.sf_source, p.pluto_dataset_version, p.year_built,
               p.house_number, p.street_name, p.pluto_address, p.pluto_numfloors,
               p.pluto_latitude, p.pluto_longitude, p.curmkttot, p.curtxbtot, p.curtrntot,
               p.curacttot, rc.category, {hav} AS distance_miles
        FROM {comp_table} p JOIN retail_class rc ON rc.parcel_id = p.parcel_id
        WHERE {' AND '.join(where)}
    """
    cand = [c for c in _rows_to_dicts(con.execute(sql, params)) if c["distance_miles"] <= cap + 1e-9]

    crit_cap = criteria.model_copy(update={
        "radius_cap_miles": cap, "radius_start_miles": min(criteria.radius_start_miles, cap)})
    radii = _radii(crit_cap)
    lo, hi = subj["sf"] * (1 - criteria.sf_band), subj["sf"] * (1 + criteria.sf_band)
    in_band = lambda c: lo <= c["sf"] <= hi
    same = lambda c: c["category"] == category

    band_applied, fallback = True, False
    # Stage 1: same-category, banded
    hit = _sweep(cand, radii, criteria.min_comp_count, predicate=lambda c: same(c) and in_band(c))
    # Stage 2: relax band, same-category
    if hit is None:
        hit = _sweep(cand, radii, criteria.min_comp_count, predicate=same)
        if hit is not None:
            band_applied = False
    # Stage 3: broader-retail fallback — same-mix preferred, band-eligible cross-use next,
    # off-band cross-use only to reach the minimum; local-first, never past cap.
    if hit is None:
        hit = _fallback_select(cand, criteria.min_comp_count, same=same, in_band=in_band)
        if hit is not None:
            fallback = True
            band_applied = all(in_band(c) for c in hit[1])
    if hit is None:
        cs = _refuse(subject_bbl, subject_summary, crit, "insufficient_comps_within_cap",
                     cap=cap, candidates=len(cand))
        return cs, meta

    radius_used, chosen = hit
    icap = icap_bbls(con, [c["parcel_id"] for c in chosen])
    comps = [_to_retail_comprow(c, category, icap) for c in chosen]
    exact_n = sum(1 for c in comps if c.match_type == "exact")
    adj = [c for c in comps if c.match_type == "adjacent"]
    breakdown: dict = {}
    for c in adj:
        breakdown[c.bucket] = breakdown.get(c.bucket, 0) + 1
    if fallback and adj:
        meta.fallback_note = _FALLBACK_NOTE
    # The band can only be "off" here because the cascade relaxed it (retail subjects have SF).
    sf_band_relaxed = bool(subj.get("sf")) and not band_applied
    cs = CompSet(subject_bbl, subject_summary, comps, len(comps), round(radius_used, 4), False,
                 crit, candidates_within_cap=len(cand), fallback_triggered=fallback,
                 exact_count=exact_n, adjacent_count=len(adj), adjacent_breakdown=breakdown,
                 sf_band_applied=band_applied, sf_band_relaxed=sf_band_relaxed)
    return cs, meta


def _to_retail_comprow(c: dict, subject_category: str, icap: set) -> CompRow:
    rd = c["retrieval_date"]
    citation = Citation(
        source_dataset=c["source_dataset"], dataset_version=c["dataset_version"],
        roll_year=c["roll_year"],
        retrieval_date=rd if isinstance(rd, date) else date.fromisoformat(str(rd)),
        parcel_id=c["parcel_id"])
    return CompRow(
        citation=citation, bldg_class=c.get("bldg_class"), bucket=c["category"],
        match_type="exact" if c["category"] == subject_category else "adjacent",
        sf=c["sf"], sf_source=c["sf_source"], sf_dataset_version=c.get("pluto_dataset_version"),
        year_built=c.get("year_built"), house_number=c.get("house_number"),
        street_name=c.get("street_name"), pluto_address=c.get("pluto_address"),
        stories=c.get("pluto_numfloors"), distance_miles=round(c["distance_miles"], 4),
        latitude=c["pluto_latitude"], longitude=c["pluto_longitude"],
        curmkttot=c.get("curmkttot"), curtxbtot=c.get("curtxbtot"),
        curtrntot=c.get("curtrntot"), curacttot=c.get("curacttot"),
        has_icap=c["parcel_id"] in icap)


def _refuse(bbl, subject, crit, note, *, cap=None, candidates=0) -> CompSet:
    return CompSet(bbl, subject, [], 0, cap, True, crit, note=note,
                   candidates_within_cap=candidates, sf_band_applied=False)


def build_retail_screen_view(con, criteria: CompCriteria, juris: Jurisdiction, *, bbl: str) -> dict:
    """Assemble the retail screen via the shared office machinery (build_screen_view), injecting
    the retail comp set + per-SF suppression + Stage-1/Stage-2 disclosures."""
    from .serialize import build_screen_view   # local import: serialize imports comps, not us
    cs, meta = select_retail_comps(con, bbl, juris, criteria)
    return build_screen_view(
        con, criteria, juris, bbl=bbl, comp_set=cs,
        suppress_per_sf=not meta.per_sf_shown, per_sf_note=meta.per_sf_note,
        classification_note=meta.classification_note, fallback_note=meta.fallback_note)
