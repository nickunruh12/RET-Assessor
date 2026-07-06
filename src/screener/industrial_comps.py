"""Industrial (F-code) comp selection — engine EXTENSION, not a parallel engine.

Mirrors retail_comps.py exactly: it selects a CompSet with industrial's class/band/cap/cascade
parameters (read from `industrial_config` in comp_criteria.json) and hands it to the SAME shared
machinery — CompRow/CompSet, compute_stats, compute_variance, build_screen_view, the per-SF
in-band percentile, and the size-dissimilar ✕ marker — that office and retail use. Only four
things here are genuinely new: the F candidate query, the subcode+borough relaxation cascade,
the Manhattan out-of-borough branch, and the (currently DORMANT) land-value coverage function.

Reused verbatim from comps.py / retail_comps.py: `_radii`, `_rows_to_dicts`, `_sweep`,
EARTH_RADIUS_MI, CompRow, CompSet, REFUSAL_MESSAGES, the icap/taxable-series lookups, and the
whole serialize/stats/variance output path.

NOT wired into the public /screen route — reachable only via the /industrial_screen +
/api/industrial_screen TEST routes (F is deliberately absent from activated_products and there
is no _screen_view interception yet), exactly how retail was staged behind /retail_screen before
its live switch. Public /screen still refuses F as out_of_scope_v1 until that flip.

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
    "sf_band": 0.75, "radius_start_miles": 0.5, "radius_cap_miles": 1.75, "radius_step_miles": 0.1,
    "min_comp_count": 8, "big_box_sf_threshold": 100000, "big_box_citywide_no_cap": True,
    "coverage_ratio_threshold": 0.30, "coverage_exclusion_threshold": 0.30,
    "subcode_match_first": True,
}

_MANHATTAN = "1"                                        # BBL first digit -> borough (1 = Manhattan)

# Disclosure strings (no verdict / banned words). Each cascade step that widens scope says so.
_CROSS_BORO_NOTE = ("Extended beyond the subject's borough to reach same-subcode industrial "
                    "comps; cross-borough comps may sit in a different submarket.")
_ALLF_NOTE = ("Extended to all industrial subcodes to reach comparable parcels (fewer than "
              "8 same-subcode comps nearby).")
_BAND_RELAX_NOTE = ("Gross-SF band relaxed to reach the 8-comp minimum; comp set includes "
                    "size-dissimilar buildings, marked below.")
_MANHATTAN_NOTE = ("Manhattan has very few industrial parcels; comp set reaches the nearest "
                   "industrial clusters in other boroughs. Cross-borough comps disclosed.")


@dataclass
class IndustrialMeta:
    subcode: str | None
    fallback_note: str | None
    quality_note: str | None          # big-box "few true peers" (reuses the prominent note slot)
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


def _pull_f_candidates(con, comp_table, subj, juris, criteria, *, cap):
    """F-code candidate pull — mirrors retail._pull_candidates (same haversine + condo/exempt
    filters) but selects class-4 F parcels directly (no class table). `cap` None = citywide."""
    slat, slon = subj["pluto_latitude"], subj["pluto_longitude"]
    hav = (f"{EARTH_RADIUS_MI}*2*asin(sqrt(power(sin(radians(p.pluto_latitude-?)/2),2)+"
           f"cos(radians(?))*cos(radians(p.pluto_latitude))*power(sin(radians(p.pluto_longitude-?)/2),2)))")
    where = ["p.parcel_id != ?",
             "p.pluto_latitude IS NOT NULL AND p.pluto_longitude IS NOT NULL",
             "p.sf IS NOT NULL", "p.bldg_class LIKE 'F%'"]
    params = [slat, slat, slon, subj["parcel_id"]]
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
    ver = subj.get("pluto_dataset_version")
    if ver:
        parts.append(f"Source: {ver}.")
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
                            comp_table: str = "parcels") -> tuple[CompSet, IndustrialMeta]:
    cfg = _cfg(criteria)
    band, minc = cfg["sf_band"], cfg["min_comp_count"]
    cap, bigbox_sf = cfg["radius_cap_miles"], cfg["big_box_sf_threshold"]
    meta = IndustrialMeta(None, None, None, None, False, None)

    subj_rows = _rows_to_dicts(con.execute(
        f"SELECT * FROM {comp_table} WHERE parcel_id = ?", [subject_bbl]))
    crit = _crit_summary(criteria, cap, band, minc)
    if not subj_rows:
        return _refuse(subject_bbl, None, crit, "subject_not_found"), meta
    subj = subj_rows[0]
    subcode = (subj.get("bldg_class") or "")
    if not subcode.startswith("F"):
        return _refuse(subject_bbl, None, crit, "out_of_scope_v1"), meta

    subject_summary = {
        "parcel_id": subj["parcel_id"], "bldg_class": subcode,
        "bucket": subcode, "bucket_label": f"Industrial — {subcode}",
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
    in_band = (lambda c: subj_sf * (1 - band) <= c["sf"] <= subj_sf * (1 + band)) if subj_sf else (lambda c: True)
    meta.suppress_per_sf = not subj_sf                 # per-SF shown unless SF missing (reuse office path)

    crit_ind = criteria.model_copy(update={
        "radius_start_miles": cfg["radius_start_miles"], "radius_cap_miles": cap,
        "radius_step_miles": cfg["radius_step_miles"]})
    radii = _radii(crit_ind)

    # ---- route: big-box (size) > Manhattan (geography) > core cascade --------------------
    if subj_sf and subj_sf >= bigbox_sf:
        sel = _select_bigbox(con, comp_table, subj, juris, criteria, subj_sf, minc, meta)
        auto_label = "Citywide — nearest big-box industrial comps, no distance cap"
    elif subject_bbl[:1] == _MANHATTAN:
        sel = _select_manhattan(con, comp_table, subj, juris, criteria, subcode, in_band,
                                radii, minc, cap, meta)
        auto_label = "Citywide — nearest industrial comps"   # out-of-borough parenthetical added below
    else:
        sel = _select_core(con, comp_table, subj, juris, criteria, subcode, in_band, radii,
                           minc, cap, meta)
        auto_label = f"Auto — expands up to {cap:g} mi"
    if sel is None:
        meta.radius_auto_label = auto_label
        return _refuse(subject_bbl, subject_summary, crit, "insufficient_comps_within_cap", cap=cap), meta
    chosen, radius_used, band_applied, sf_band_relaxed, fallback, candidates_n = sel
    # Manhattan label claims out-of-borough reach ONLY when a comp actually crossed (same gate
    # as _MANHATTAN_NOTE); an all-Manhattan cluster keeps the accurate in-borough label.
    if subject_bbl[:1] == _MANHATTAN and any(c["parcel_id"][:1] != subject_bbl[:1] for c in chosen):
        auto_label += " (Manhattan reaches out-of-borough)"
    meta.radius_auto_label = auto_label

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


def _select_core(con, comp_table, subj, juris, criteria, subcode, in_band, radii, minc, cap, meta):
    """Non-Manhattan cascade (item 7), geography relaxes BEFORE subcode; each step disclosed:
    same-subcode in-borough -> same-subcode cross-borough -> all-F cross-borough -> band-relax
    -> refuse. Distance never exceeds the cap; the band-relax fill is size-dissimilar-flagged."""
    pool = _pull_f_candidates(con, comp_table, subj, juris, criteria, cap=cap)
    boro = subj["parcel_id"][:1]
    same_sub = lambda c: c["bldg_class"] == subcode
    same_boro = lambda c: c["parcel_id"][:1] == boro

    hit = _sweep(pool, radii, minc, predicate=lambda c: same_sub(c) and same_boro(c) and in_band(c))
    note, fallback = None, False
    if hit is None:
        hit = _sweep(pool, radii, minc, predicate=lambda c: same_sub(c) and in_band(c))
        if hit is not None:
            note = _CROSS_BORO_NOTE
    if hit is None:
        hit = _sweep(pool, radii, minc, predicate=in_band)
        if hit is not None:
            note, fallback = _ALLF_NOTE, True
    if hit is not None:
        radius_used, chosen = hit
        meta.fallback_note = note
        return chosen, radius_used, True, False, fallback, len(pool)
    # band-relax: nearest all-F within cap (size-dissimilar), fill to the minimum
    chosen = sorted(pool, key=lambda c: c["distance_miles"])[:minc]
    if len(chosen) < minc:
        return None
    meta.fallback_note = _BAND_RELAX_NOTE
    return chosen, max(c["distance_miles"] for c in chosen), False, True, True, len(pool)


def _select_manhattan(con, comp_table, subj, juris, criteria, subcode, in_band, radii, minc, cap, meta):
    """Manhattan (item 8): in-borough same-subcode ±band first; else reach the NEAREST
    out-of-borough same-subcode comps citywide, then fill with nearest all-F; refuse only if
    the whole city can't field 8 (never, in practice). Every cross-borough reach disclosed."""
    capped = _pull_f_candidates(con, comp_table, subj, juris, criteria, cap=cap)
    hit = _sweep(capped, radii, minc,
                 predicate=lambda c: c["bldg_class"] == subcode and c["parcel_id"][:1] == _MANHATTAN and in_band(c))
    if hit is not None:                                # rare: Manhattan fills locally
        radius_used, chosen = hit
        return chosen, radius_used, True, False, False, len(capped)

    citywide = _pull_f_candidates(con, comp_table, subj, juris, criteria, cap=None)
    same = sorted((c for c in citywide if c["bldg_class"] == subcode), key=lambda c: c["distance_miles"])
    chosen = same[:minc]
    ids = {c["parcel_id"] for c in chosen}
    if len(chosen) < minc:                             # top up with nearest all-F citywide
        rest = sorted((c for c in citywide if c["parcel_id"] not in ids), key=lambda c: c["distance_miles"])
        chosen += rest[:minc - len(chosen)]
    if len(chosen) < minc:
        return None
    # Fire the cross-borough note ONLY when a comp actually left the subject's borough — the
    # citywide-nearest step can still land an all-Manhattan cluster (e.g. 1007880016), and
    # claiming "other boroughs" then would be false. Same borough test the shared cross-borough
    # note uses (BBL first digit); if nothing crossed, no note.
    subj_boro = subj["parcel_id"][:1]
    if any(c["parcel_id"][:1] != subj_boro for c in chosen):
        meta.fallback_note = _MANHATTAN_NOTE
    band_applied = all(in_band(c) for c in chosen)
    return chosen, max(c["distance_miles"] for c in chosen), band_applied, not band_applied, True, len(citywide)


def _select_bigbox(con, comp_table, subj, juris, criteria, subj_sf, minc, meta):
    """Big-box (item 9, ≥ big_box_sf_threshold): drop the band, take the nearest-BY-SIZE F
    parcels CITYWIDE (no distance cap) — the retail K8 pattern, keyed on size instead of pure
    distance. Mandatory 'few true peers' disclosure + max comp distance; loud size flags."""
    pool = _pull_f_candidates(con, comp_table, subj, juris, criteria, cap=None)
    chosen = sorted(pool, key=lambda c: abs(c["sf"] - subj_sf))[:minc]
    if len(chosen) < minc:
        return None
    maxd = max(c["distance_miles"] for c in chosen)
    meta.quality_note = (
        "Big-box industrial has very few true peers in NYC. This is a size-matched citywide "
        "screen — the subject is compared against the nearest-sized industrial parcels "
        f"regardless of distance (furthest comp {maxd:.1f} mi). Treat the position read as "
        "directional, not precise; size-dissimilar comps are marked below.")
    return chosen, maxd, False, True, True, len(pool)


def build_industrial_screen_view(con, criteria: CompCriteria, juris: Jurisdiction, *, bbl: str) -> dict:
    """Assemble the industrial screen via the SHARED office/retail machinery (build_screen_view),
    injecting the industrial comp set + disclosures. No new render path."""
    from .serialize import build_screen_view          # local import: serialize imports comps, not us
    cs, meta = select_industrial_comps(con, bbl, juris, criteria)
    # Coverage note (when it ever fires) rides alongside the cascade fallback note in the same
    # disclosure slot retail uses; today it is always None (LotArea not loaded).
    fallback = " ".join(n for n in (meta.fallback_note, meta.coverage_note) if n) or None
    return build_screen_view(
        con, criteria, juris, bbl=bbl, comp_set=cs,
        suppress_per_sf=meta.suppress_per_sf, per_sf_note=None,
        classification_note=None, fallback_note=fallback,
        quality_note=meta.quality_note, radius_auto_label=meta.radius_auto_label)
