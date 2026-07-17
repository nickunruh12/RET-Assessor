"""Industrial (pooled E+F) comp selection — engine EXTENSION, not a parallel engine.

Mirrors retail_comps.py exactly: it selects a CompSet with industrial's band/cap/cascade
parameters (read from `industrial_config` in comp_criteria.json) and hands it to the SAME shared
machinery — CompRow/CompSet, compute_stats, compute_variance, build_screen_view, the per-SF
in-band percentile, and the size-dissimilar ✕ marker — that office and retail use.

POOLED E+F (restructured 2026-07-17; DECISIONS 'Pooled Industrial route'): the E/F split is a
DOF filing artifact (construction/fireproofing), not an asset boundary. Measured: the eight
subcodes E1,E2,E9,F1,F2,F4,F5,F9 sit in one $112–123/SF band; after matching size (±75%) and
location (≤1 mi), storage-vs-production explains 1.5% of per-SF variance (R² 0.015 — below the
already-killed vintage filter at 0.019); E and F interleave block-by-block (F→nearest-E median
0.03 mi); pooling drops F's refusals ~4× and improves everyone's reach. So the eight are ONE
FLAT POOL. Fallback is same-subcode-first → flat pool → refuse — NOT a family/subcode tier (a
subcode preference would reorder comps toward a non-driver, the exact failure mode of the soft
vintage preference we rejected).

RADIUS = shortfall-triggered extension (restructured 2026-07-17; DECISIONS 'shortfall
extended radius'). No size threshold anywhere. The cascade first tries to reach 8 in-band
comps within the STANDARD cap (radius_cap_miles, 1.75 mi); a subject that falls short EXTENDS
to the extended cap (radius_cap_extended_miles, 4.0 mi) at the SAME ±75% band, then REFUSES.
Size-agnostic: the trigger is the density shortfall, not a size gate (measured — no per-SF
regime change at any size, and 4.0 mi is the fill knee for the large tail). This REPLACES the
dead 100K big-box branch (which invented scarcity: 90% of ≥100K fills locally, and a 654K
fixture fills at 0.6 mi). It also RETIRES the Manhattan out-of-borough branch: the 4.0 mi
extension covers 7 of 8 Manhattan stragglers, and the 1 remaining refuses honestly.

TWO flagged members inside the route, both measured distinct:
  * E7 self-storage (median $175/SF, QCD 0.057 — 5× tighter, coverage 2.69, median 79K SF):
    SAME-SUBCODE-ONLY, never falls back to the pool; refuses when it can't fill 8. The ±75%
    band is DROPPED for E7 (size is a total non-driver of E7 per-SF: R² 0.000, flat because
    self-storage prices per unit-month) — any E7 within the radius is a comp, radius is the
    only guard. Product label reads "Self-Storage", not "Industrial". ONE branch, not an
    engine. E7 still gets the 1.75→4.0 mi extension.
  * F8 tank farm (structurally land-dominant, ~16 parcels): an F8 SUBJECT falls back to the
    flat pool (F8 is NOT in the pool itself); its own per-SF stays withheld when land-dominant
    via the existing 0.30 coverage rule. No new handling.

Reused verbatim from comps.py / retail_comps.py: `_radii`, `_rows_to_dicts`, `_sweep`,
EARTH_RADIUS_MI, CompRow, CompSet, REFUSAL_MESSAGES, the icap/taxable-series lookups, and the
whole serialize/stats/variance output path (incl. the shared cross-borough note).

LIVE on the public /screen + /api/screen routes: a resolved E- or F-code is intercepted in
_screen_view and routed here, the same K-only pattern retail uses (the broad out_of_scope_v1
gate is untouched, so every non-office/non-K/non-E/non-F class keeps refusing). The
/industrial_screen + /api/industrial_screen routes are kept for debugging.

Band note: industrial SELECTS comps at ±sf_band (0.75). The per-SF percentile / ✕ marker keep
the shared "size-comparable" definition (criteria.sf_band, 0.50) — but that only engages on
band-RELAXED sets (sf_band_relaxed=True), where the tighter definition is the conservative,
honest choice. On a normal in-band set nothing is flagged and the percentile uses the full pool.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .abatements import icap_bbls
from .comps import (
    EARTH_RADIUS_MI,
    CompRow,
    CompSet,
    REFUSAL_MESSAGES,
    _radii,
    _rows_to_dicts,
)
from .jurisdiction import CompCriteria, Jurisdiction
from .retail_comps import _sweep                      # reuse retail's radius sweep verbatim
from .schema import Citation
from .taxable_series import taxable_series

# Config defaults mirror comp_criteria.json industrial_config; the file is the source of truth.
_DEFAULTS = {
    "sf_band": 0.75, "radius_start_miles": 0.5, "radius_cap_miles": 1.75,
    "radius_cap_extended_miles": 4.0, "radius_step_miles": 0.1,
    "min_comp_count": 8,
    "coverage_ratio_threshold": 0.30, "coverage_exclusion_threshold": 0.30,
    "subcode_match_first": True,
}

# The FLAT POOL — the eight measured-equivalent subcodes (E7 and F8 deliberately excluded;
# both are handled as flagged special cases below). ~8,968 parcels.
POOL_SUBCODES = ("E1", "E2", "E9", "F1", "F2", "F4", "F5", "F9")
E7 = "E7"                                              # self-storage: same-subcode-only, walled

# Cleaned market names (BARE — no DOF code baked in; the code is prepended by callers so the
# mapping stays traceable without double-wrapping). No em-dash inside these: they sit inside
# parentheticals that already carry one.
_SUBCODE_LABELS = {
    "E1": "Warehouse", "E2": "Contractor's Warehouse", "E9": "Misc Warehouse",
    "E7": "Self-Storage",
    "F1": "Heavy Manufacturing", "F2": "Special Construction", "F4": "Industrial",
    "F5": "Light Manufacturing", "F8": "Tank Farm", "F9": "Misc Industrial",
}


def _clean_name(subcode: str | None) -> str:
    """'F5' -> 'Light Manufacturing' (bare market name, no code). Falls back to the code."""
    sc = (subcode or "").strip()
    return _SUBCODE_LABELS.get(sc, sc or "Industrial")


def _label(subcode: str | None) -> str:
    """'F5' -> 'F5 Light Manufacturing' (code + bare name, no parens). Used where the label
    sits inside a list or a parenthetical, so it must not add its own parentheses."""
    sc = (subcode or "").strip()
    name = _SUBCODE_LABELS.get(sc)
    return f"{sc} {name}" if name else (sc or "Industrial")


def _product_label(subcode: str | None) -> str:
    """Route/product name: 'Self-Storage' for E7, 'Industrial' for the pooled eight + F8."""
    return "Self-Storage" if (subcode or "").strip() == E7 else "Industrial"


def _bucket_label(subcode: str | None) -> str:
    """The subject-panel bucket label WITHOUT the leading code (the template prepends the code
    as 'CODE (bucket_label)'): E7 -> 'Self-Storage' (the route IS the clean name); every other
    subcode -> 'Industrial — Warehouse' (route — clean name)."""
    sc = (subcode or "").strip()
    if sc == E7:
        return "Self-Storage"
    return f"Industrial — {_clean_name(sc)}"


def _universe_subcodes(subcode: str) -> tuple[str, ...]:
    """Candidate subcodes to PULL for a subject of this subcode. E7 is walled to itself; every
    other subject sees the flat pool plus its own subcode (so an F8 subject can reach its own
    same-subcode step even though F8 is not in the pool)."""
    if subcode == E7:
        return (E7,)
    return tuple(dict.fromkeys((*POOL_SUBCODES, subcode)))   # pool ∪ {subcode}, order-stable


def _pool_fallback_subcodes(subcode: str) -> tuple[str, ...]:
    """Subcodes the flat-pool fallback step may draw from. E7 never leaves E7 (empty cross-pool);
    everyone else falls back to the eight (F8 included as a subject falls back here, not to F8)."""
    return (E7,) if subcode == E7 else POOL_SUBCODES


# Disclosure strings (no verdict / banned words). The extension says how far it actually reached.
def _extended_note(radius_used: float, cap: float) -> str:
    return (f"Comp set reached beyond the standard {cap:g}-mile search to {radius_used:.1f} miles "
            "to find 8 comparable parcels; the nearest 8 within that radius were used.")


def _composition_note(subject_subcode: str, comps) -> str | None:
    """Name the subcode mix whenever ANY comp differs from the subject's subcode; say nothing
    when the set is pure. A count is a fact — no threshold (same precedent as the cross-type
    note). Names every subcode present, subject's own first, then others by count desc."""
    if not comps:
        return None
    counts: dict[str, int] = {}
    for c in comps:
        sc = (c.bldg_class or "").strip()
        counts[sc] = counts.get(sc, 0) + 1
    if all(sc == subject_subcode for sc in counts):
        return None                                    # pure set — say nothing
    ordered = sorted(counts.items(), key=lambda kv: (kv[0] != subject_subcode, -kv[1], kv[0]))
    listed = ", ".join(f"{n} {_label(sc)}" for sc, n in ordered)
    return (f"Comp set spans multiple industrial subcodes — {len(comps)} comps: {listed}. "
            "Subcodes are a DOF filing distinction, not a value boundary; comps are pooled on "
            "size and location.")


@dataclass
class IndustrialMeta:
    subcode: str | None
    fallback_note: str | None
    extended: bool                    # True when the shortfall extension (>1.75mi) fired
    radius_auto_label: str | None
    suppress_per_sf: bool
    coverage_note: str | None         # DORMANT until PLUTO LotArea is loaded (see build view)


def _cfg(criteria: CompCriteria) -> dict:
    c = dict(_DEFAULTS)
    c.update(criteria.industrial_config or {})
    return c


def _crit_summary(criteria, cap, band, minc):
    return {"product": "industrial", "sf_band": band, "radius_cap_miles": cap,
            "min_comp_count": minc, "match": "F-subcode (same-subcode first)"}


def _pull_candidates(con, comp_table, subj, juris, criteria, *, cap, subcodes):
    """Pooled-industrial candidate pull — mirrors retail._pull_candidates (same haversine +
    condo/exempt filters) but selects class-4 parcels whose bldg_class is in `subcodes` (the
    pull universe for this subject). `cap` None = citywide."""
    slat, slon = subj["pluto_latitude"], subj["pluto_longitude"]
    hav = (f"{EARTH_RADIUS_MI}*2*asin(sqrt(power(sin(radians(p.pluto_latitude-?)/2),2)+"
           f"cos(radians(?))*cos(radians(p.pluto_latitude))*power(sin(radians(p.pluto_longitude-?)/2),2)))")
    subcode_ph = ",".join(["?"] * len(subcodes))
    where = ["p.parcel_id != ?",
             "p.pluto_latitude IS NOT NULL AND p.pluto_longitude IS NOT NULL",
             "p.sf IS NOT NULL", f"p.bldg_class IN ({subcode_ph})"]
    params = [slat, slat, slon, subj["parcel_id"], *subcodes]
    condo_sql, condo_params = juris.condo_clause(criteria)
    where.append(condo_sql.replace("parcel_id", "p.parcel_id").replace("bldg_class", "p.bldg_class"))
    params += condo_params
    if criteria.exclude_non_positive_market_value:
        where.append("p.curmkttot > 0")
    cols = ("SELECT p.parcel_id, p.source_dataset, p.dataset_version, p.roll_year, "
            "p.retrieval_date, p.bldg_class, p.zip_code, p.sf, p.sf_source, "
            "p.pluto_dataset_version, p.pluto_bldgarea, p.pluto_lotarea, p.year_built, "
            "p.house_number, p.street_name, p.pluto_address, p.pluto_numfloors, "
            "p.pluto_latitude, p.pluto_longitude, "
            "p.curmkttot, p.curtxbtot, p.curtrntot, p.curacttot, "
            f"{hav} AS distance_miles")
    sql = f"{cols} FROM {comp_table} p WHERE {' AND '.join(where)}"
    rows = _rows_to_dicts(con.execute(sql, params))
    return rows if cap is None else [c for c in rows if c["distance_miles"] <= cap + 1e-9]


# --- land-value coverage (item 5) ------------------------------------------------------------
# Two complementary, non-contradictory disclosures share the 0.30 measurement:
#   * SUBJECT land-dominant  -> the subject's OWN per-SF is caveated (coverage_note, here).
#   * COMPS  land-dominant   -> those comps are EXCLUDED from the per-SF calc (stats/serialize).
# The comp-side is NOT described here anymore (it used to say "N comps also land-dominant",
# which implied they were still in the stats — they are not).
def coverage_ratio(bldgarea, lotarea):
    """BldgArea / LotArea, or None when either is missing/zero. Display-only, never comp math."""
    return (bldgarea / lotarea) if (bldgarea and lotarea and lotarea > 0) else None


def coverage_note(subj_cov, threshold) -> str | None:
    """SUBJECT-side caveat: fires when the SUBJECT's own coverage < threshold, so its own per-SF
    is skewed by land value. Comp-side land-dominance is handled by the per-SF EXCLUSION, not
    here. F8 subjects (median coverage ~0.08) fire this near-universally — intended."""
    if subj_cov is None or subj_cov >= threshold:
        return None
    return ("This parcel is land-dominant: its building covers a small share of the lot "
            f"(building-area ÷ lot-area under {threshold:g}), so the subject's own per-SF is "
            "skewed by land value — read its per-SF position with that caveat.")


def _coverage_display(subj: dict, subj_cov, threshold) -> str | None:
    """The rendered SUBJECT-side coverage disclosure: caveat text + the subject's concrete
    BldgArea/LotArea ratio, cited to PLUTO. None when the subject is not land-dominant."""
    base = coverage_note(subj_cov, threshold)
    if base is None:
        return None
    parts = [base]
    ba, la = subj.get("pluto_bldgarea"), subj.get("pluto_lotarea")
    if subj_cov is not None and ba and la:
        parts.append(f"Subject: building-area {ba:,.0f} SF ÷ lot-area {la:,.0f} SF = {subj_cov:.2f}.")
    # The PLUTO dataset citation is intentionally NOT stamped inline here — machine provenance
    # belongs in the provenance block (sf_pluto_versions), not mid-prose. The concrete
    # BldgArea/LotArea figures above stay; they are the readable fact, not a raw version string.
    return " ".join(parts)


def _to_industrial_comprow(c: dict, subject_subcode: str, icap: set, land_dominant_thr: float) -> CompRow:
    rd = c["retrieval_date"]
    citation = Citation(
        source_dataset=c["source_dataset"], dataset_version=c["dataset_version"],
        roll_year=c["roll_year"],
        retrieval_date=rd if isinstance(rd, date) else date.fromisoformat(str(rd)),
        parcel_id=c["parcel_id"])
    cov = coverage_ratio(c.get("pluto_bldgarea"), c.get("pluto_lotarea"))
    return CompRow(
        citation=citation, bldg_class=c.get("bldg_class"), bucket=c["bldg_class"],
        match_type="exact" if c["bldg_class"] == subject_subcode else "adjacent",
        sf=c["sf"], sf_source=c["sf_source"], sf_dataset_version=c.get("pluto_dataset_version"),
        year_built=c.get("year_built"), house_number=c.get("house_number"),
        street_name=c.get("street_name"), pluto_address=c.get("pluto_address"),
        stories=c.get("pluto_numfloors"), distance_miles=round(c["distance_miles"], 4),
        latitude=c["pluto_latitude"], longitude=c["pluto_longitude"],
        curmkttot=c.get("curmkttot"), curtxbtot=c.get("curtxbtot"),
        curtrntot=c.get("curtrntot"), curacttot=c.get("curacttot"),
        has_icap=c["parcel_id"] in icap,
        land_dominant=cov is not None and cov < land_dominant_thr)


def _refuse(bbl, subject, crit, note, *, cap=None, candidates=0) -> CompSet:
    return CompSet(bbl, subject, [], 0, cap, True, crit, note=note,
                   candidates_within_cap=candidates, sf_band_applied=False)


def select_industrial_comps(con, subject_bbl: str, juris: Jurisdiction, criteria: CompCriteria,
                            comp_table: str = "parcels", *,
                            radius_override: float | None = None) -> tuple[CompSet, IndustrialMeta]:
    cfg = _cfg(criteria)
    # Manual radius override (slider): BOUND the whole cascade at R — the standard cap AND the
    # shortfall extension are both pinned to R, so the 8-comp refusal gate genuinely fires when
    # the user tightens the search. No override -> auto behavior (standard cap 1.75, extension
    # to 4.0 on a shortfall).
    if radius_override is not None:
        cfg = {**cfg, "radius_start_miles": radius_override,
               "radius_cap_miles": radius_override, "radius_cap_extended_miles": radius_override}
    band, minc = cfg["sf_band"], cfg["min_comp_count"]
    cap, cap_ext = cfg["radius_cap_miles"], cfg["radius_cap_extended_miles"]
    meta = IndustrialMeta(None, None, False, None, False, None)

    subj_rows = _rows_to_dicts(con.execute(
        f"SELECT * FROM {comp_table} WHERE parcel_id = ?", [subject_bbl]))
    crit = _crit_summary(criteria, cap, band, minc)
    if not subj_rows:
        return _refuse(subject_bbl, None, crit, "subject_not_found"), meta
    subj = subj_rows[0]
    subcode = (subj.get("bldg_class") or "")
    # Scope: any class-4 E- or F-code. E7 (self-storage) is walled to same-subcode-only; F8 is a
    # normal subject that falls back to the pool. Everything non-E/F stays out of scope.
    if not (subcode.startswith("E") or subcode.startswith("F")):
        return _refuse(subject_bbl, None, crit, "out_of_scope_v1"), meta
    is_e7 = subcode == E7
    product = _product_label(subcode)

    subject_summary = {
        "parcel_id": subj["parcel_id"], "bldg_class": subcode,
        "bucket": subcode, "bucket_label": _bucket_label(subcode),
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
    }
    if criteria.exclude_non_positive_market_value and not (subj.get("curmkttot") and subj["curmkttot"] > 0):
        return _refuse(subject_bbl, subject_summary, crit, "subject_tax_exempt"), meta
    if subj.get("pluto_latitude") is None or subj.get("pluto_longitude") is None:
        return _refuse(subject_bbl, subject_summary, crit, "subject_no_coordinates"), meta

    subj_sf = subj.get("sf")
    # E7 drops the ±75% band entirely: size is a total non-driver of E7 per-SF (R² 0.000, flat —
    # self-storage prices per unit-month), so any E7 within the radius is a valid comp and the
    # radius is the only guard. The pooled eight KEEP the band (it guards the ABSOLUTE value/tax
    # charts, where size explains ~87% of total EMV).
    if is_e7:
        in_band = lambda c: True
    elif subj_sf:
        in_band = lambda c: subj_sf * (1 - band) <= c["sf"] <= subj_sf * (1 + band)
    else:
        in_band = lambda c: True
    meta.suppress_per_sf = not subj_sf                 # per-SF shown unless SF missing (reuse office path)

    # Two radius ladders: standard (≤cap) and extended (≤cap_ext). The cascade fills within the
    # standard ladder first; only a shortfall reaches into the extended tail.
    crit_ext = criteria.model_copy(update={
        "radius_start_miles": cfg["radius_start_miles"], "radius_cap_miles": cap_ext,
        "radius_step_miles": cfg["radius_step_miles"]})
    radii_ext = _radii(crit_ext)
    radii_std = [r for r in radii_ext if r <= cap + 1e-9]

    # Pull universe + flat-pool fallback set for this subject (E7 walled to itself).
    pull_subcodes = _universe_subcodes(subcode)
    pool_fallback = _pool_fallback_subcodes(subcode)

    # ---- ONE cascade for everyone: same-subcode → flat pool → extend to cap_ext → refuse.
    # No size branch (big-box removed) and no Manhattan branch (the extension supersedes both).
    sel = _select_core(con, comp_table, subj, juris, criteria, subcode, in_band,
                       radii_std, radii_ext, minc, cap, cap_ext, meta,
                       pull_subcodes=pull_subcodes, pool_fallback=pool_fallback)
    if sel is None:
        meta.radius_auto_label = f"Auto — expands up to {cap_ext:g} mi"
        return _refuse(subject_bbl, subject_summary, crit, "insufficient_comps_within_cap", cap=cap_ext), meta
    chosen, radius_used, band_applied, sf_band_relaxed, fallback, candidates_n = sel
    # Auto-mode label + extension disclosure (only for AUTO runs — a manual override radius is the
    # user's own choice, not a tool extension, so it never claims to have "reached beyond").
    if radius_override is None and meta.extended:
        meta.fallback_note = _extended_note(radius_used, cap)
        meta.radius_auto_label = f"Auto — reached {radius_used:.1f} mi (beyond the {cap:g}-mi standard)"
    else:
        meta.radius_auto_label = f"Auto — expands up to {cap:g} mi"

    icap = icap_bbls(con, [c["parcel_id"] for c in chosen])
    excl_thr = cfg["coverage_exclusion_threshold"]     # comp-side: EXCLUDE from per-SF (separate key)
    comps = [_to_industrial_comprow(c, subcode, icap, excl_thr) for c in chosen]
    exact_n = sum(1 for c in comps if c.match_type == "exact")
    adj = [c for c in comps if c.match_type == "adjacent"]
    breakdown: dict = {}
    for c in adj:
        breakdown[c.bucket] = breakdown.get(c.bucket, 0) + 1

    # Coverage (item 5) — SUBJECT-side caveat only. Uses PLUTO BldgArea ÷ PLUTO LotArea (both
    # from the same PLUTO release, so the ratio and the threshold share provenance; the roll's
    # land_area is deliberately NOT used). The comp-side land-dominance is the per-SF EXCLUSION
    # above (land_dominant flags), disclosed by serialize — NOT repeated here. Separate config
    # key from the exclusion threshold so the two tune independently (deliberately 0.30 now).
    cov_thr = cfg["coverage_ratio_threshold"]
    subj_cov = coverage_ratio(subj.get("pluto_bldgarea"), subj.get("pluto_lotarea"))
    meta.coverage_note = _coverage_display(subj, subj_cov, cov_thr)
    # SAME trigger, one boolean: when the subject is land-dominant its own per-SF is meaningless
    # (tiny building, land-driven value), so the stats layer withholds the subject's per-SF point
    # + percentile. Reuses subj_cov (no new coverage computation); read via cs.subject downstream.
    subject_summary["subject_land_dominant"] = bool(subj_cov is not None and subj_cov < cov_thr)

    cs = CompSet(subject_bbl, subject_summary, comps, len(comps), round(radius_used, 4), False,
                 crit, candidates_within_cap=candidates_n, fallback_triggered=fallback,
                 exact_count=exact_n, adjacent_count=len(adj), adjacent_breakdown=breakdown,
                 sf_band_applied=band_applied, sf_band_relaxed=sf_band_relaxed)
    return cs, meta


def _select_core(con, comp_table, subj, juris, criteria, subcode, in_band, radii_std, radii_ext,
                 minc, cap, cap_ext, meta, *, pull_subcodes, pool_fallback):
    """The ONE cascade: same-subcode → flat pool (both within the standard cap) → extend to the
    extended cap at the SAME band → refuse. NOT a subcode tier — the sweep orders by distance, so
    nearer comps are preferred naturally, and the shared serializer discloses any borough
    crossing. The band is NEVER widened (no band-relax): a shortfall reaches further at the same
    ±75% band, or refuses. E7 has pool_fallback == its own subcode (the pool step is a no-op) and
    a dropped band (in_band always True), so it is same-subcode-only same-guard.

    Returns (chosen, radius_used, band_applied, sf_band_relaxed, fallback, candidate_count).
    sf_band_relaxed is always False now (the band is never widened); meta.extended records the
    shortfall extension for disclosure."""
    pool = _pull_candidates(con, comp_table, subj, juris, criteria, cap=cap_ext, subcodes=pull_subcodes)
    same_sub = lambda c: c["bldg_class"] == subcode
    in_pool = lambda c: c["bldg_class"] in pool_fallback
    has_pool_step = pool_fallback != (subcode,)

    # STANDARD cap (≤ cap): same-subcode-first, then the flat pool.
    hit = _sweep(pool, radii_std, minc, predicate=lambda c: same_sub(c) and in_band(c))
    fallback = False
    if hit is None and has_pool_step:
        hit = _sweep(pool, radii_std, minc, predicate=lambda c: in_pool(c) and in_band(c))
        fallback = hit is not None
    # EXTENSION (cap < r ≤ cap_ext): density shortfall — nearest in-band pool at the same band.
    # Location-first here (no subcode re-preference): subcode is a non-driver, distance matters.
    if hit is None:
        hit = _sweep(pool, radii_ext, minc, predicate=lambda c: in_pool(c) and in_band(c))
        if hit is not None:
            fallback = True
            meta.extended = True
    if hit is None:
        return None                                    # refuse — 8 in-band unreachable within cap_ext
    radius_used, chosen = hit
    return chosen, radius_used, True, False, fallback, len(pool)


def build_industrial_screen_view(con, criteria: CompCriteria, juris: Jurisdiction, *, bbl: str,
                                 radius_selection: str = "default") -> dict:
    """Assemble the industrial screen via the SHARED office/retail machinery (build_screen_view),
    injecting the industrial comp set + disclosures. No new render path.

    `radius_selection` carries the slider state: 'default' = auto (config cap 1.75, citywide tails
    free); a numeric string R = manual override that BOUNDS the whole cascade at R (mirrors office)."""
    from .serialize import build_screen_view          # local import: serialize imports comps, not us
    override = None
    if radius_selection != "default":
        try:
            override = float(radius_selection)
        except ValueError:
            override = None
    cs, meta = select_industrial_comps(con, bbl, juris, criteria, radius_override=override)
    # Composition disclosure: name the subcode mix whenever any comp differs from the subject's
    # subcode (item 5). Rides in the same disclosure slot as the cascade + coverage notes.
    subj_subcode = (cs.subject or {}).get("bldg_class", "") if cs.subject else ""
    composition = _composition_note(subj_subcode, cs.comps) if not cs.refused else None
    fallback = " ".join(n for n in (composition, meta.fallback_note, meta.coverage_note) if n) or None
    result = build_screen_view(
        con, criteria, juris, bbl=bbl, comp_set=cs,
        suppress_per_sf=meta.suppress_per_sf, per_sf_note=None,
        classification_note=None, fallback_note=fallback,
        quality_note=None, radius_auto_label=meta.radius_auto_label,
        radius_selection=radius_selection)
    # Industrial-only post-processing (office/retail never call this path, so it cannot move
    # their output): stamp the product label, and enrich the comp table's cross-subcode marker
    # with the cleaned name — "✗ (F5)" -> "✗ (F5 Light Manufacturing)" — so the table carries
    # subcode + cleaned name. Same-subcode "✓" rows are left untouched (the subject's own name
    # is in the subject panel's bucket label).
    if isinstance(result, dict) and result.get("status") == "ok":
        result["product_label"] = _product_label(subj_subcode)
        for _rows in ([v["rows"] for v in result.get("variance", {}).get("views", [])]
                      + [result.get("variance", {}).get("all_diffs", [])]):
            for _r in _rows:
                disp = _r.get("exact_match_display", "")
                if disp.startswith("✗ (") and disp.endswith(")"):
                    sc = disp[3:-1]
                    name = _SUBCODE_LABELS.get(sc)
                    if name:
                        _r["exact_match_display"] = f"✗ ({sc} {name})"
    return result
