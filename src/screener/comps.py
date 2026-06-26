"""Comp-selection engine — jurisdiction-agnostic. NO statistics.

Given a subject BBL it returns the set of comparable parcels, the radius used, and a
count. It does the generic work — scope check, gross-SF band, great-circle distance,
radius-first expansion, excluding the subject, carrying provenance — and delegates
jurisdiction-specific predicates (product scope, office bucketing, condo exclusion)
to a `Jurisdiction` plugin.

Selection logic only. NOTHING statistical: no mean, median, percentile, ranking by
value. Distance ranking is for *selection* (who is near enough), not analytics.

Radius-first logic (DECISIONS 2026-06-19): collect all qualifying comps within
`radius_start_miles`; if fewer than `min_comp_count`, expand by `radius_step_miles`
toward `radius_cap_miles`; if still short at the cap, REFUSE. The actual radius used
is reported on every result.

Every comp row is a `CompRow` (subclasses `CitedRow`), so a comp without its
provenance tuple cannot exist; each also carries the PLUTO version of its SF value.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date

import duckdb

from . import config
from .jurisdiction import CompCriteria, Jurisdiction, get_jurisdiction
from .schema import Citation, CitedRow

# Mean Earth radius in miles (for the haversine great-circle distance).
EARTH_RADIUS_MI = 3958.7613

# Human-readable messages for refusal notes (no rendering layer yet; surfaced for
# validation and carried so downstream display stays consistent).
REFUSAL_MESSAGES = {
    "subject_not_found": "no parcel found for this BBL",
    "out_of_scope_v1": "out of scope for v1 (only office is activated)",
    "subject_tax_exempt": "this parcel has no positive market value (tax-exempt); "
                          "assessment comparison does not apply",
    "subject_no_coordinates": "this parcel has no PLUTO coordinates; cannot rank comps by distance",
    "insufficient_comps_within_cap": "insufficient comparable properties within 1 mile",
}


def refusal_message(note: str | None) -> str | None:
    return REFUSAL_MESSAGES.get(note) if note else None


class CompRow(CitedRow):
    """One comparable parcel. Carries the citation tuple (via CitedRow) + comp fields.

    `match_type` ('exact' | 'adjacent') records whether this comp shares the subject's
    exact class (or grouped bucket) or was pulled in via the fallback ladder, alongside
    its actual `bldg_class` — the same provenance discipline as the citation tuple.

    The gross-SF value also cites its own source: `sf_source` + `sf_dataset_version`
    (PLUTO version when sf came from BldgArea), honoring the $/SF output contract.
    """

    bldg_class: str | None
    bucket: str | None
    match_type: str             # "exact" or "adjacent"
    sf: float
    sf_source: str
    sf_dataset_version: str | None
    year_built: str | None      # DISPLAY ONLY (68% fill); never used to rank or sort
    house_number: str | None    # roll display-address (primary)
    street_name: str | None
    pluto_address: str | None   # PLUTO display-address (fallback)
    stories: float | None       # PLUTO NumFloors — DISPLAY ONLY; never used to rank or sort
    distance_miles: float
    latitude: float
    longitude: float
    curmkttot: float | None
    curtxbtot: float | None
    curtrntot: float | None
    curacttot: float | None


@dataclass
class CompSet:
    subject_bbl: str
    subject: dict | None
    comps: list[CompRow]
    count: int
    radius_used_miles: float | None
    refused: bool
    criteria: dict
    note: str | None = None     # out_of_scope_v1 / subject_not_found / insufficient_comps_within_cap
    candidates_within_cap: int = 0  # diagnostic: qualifying comps inside the 1-mile cap
    sf_band_applied: bool = True    # False when subject lacks gross SF (no size match)
    # fallback accounting (the non-negotiable exact-vs-adjacent labeling)
    fallback_triggered: bool = False
    exact_count: int = 0
    adjacent_count: int = 0
    adjacent_breakdown: dict = field(default_factory=dict)  # class -> count

    def composition_label(self) -> str:
        """One-line exact-vs-adjacent summary, e.g.
        '8 comps: 5 exact (O3), 3 adjacent (2 O2, 1 O1), radius 0.8 mi'."""
        if self.refused or not self.comps:
            return f"{self.count} comps"
        subj_cls = self.subject["bldg_class"] if self.subject else "?"
        if not self.fallback_triggered:
            return f"{self.count} comps: all {self.exact_count} exact ({subj_cls}), radius {self.radius_used_miles} mi"
        adj = ", ".join(f"{n} {c}" for c, n in sorted(self.adjacent_breakdown.items(),
                                                       key=lambda kv: (-kv[1], kv[0])))
        return (f"{self.count} comps: {self.exact_count} exact ({subj_cls}), "
                f"{self.adjacent_count} adjacent ({adj}), radius {self.radius_used_miles} mi")


# --------------------------------------------------------------------------- #
def _rows_to_dicts(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _refusal(subject_bbl, subject, criteria, note, cap=None) -> CompSet:
    return CompSet(subject_bbl, subject, [], 0, cap, True, criteria, note=note)


def _radii(criteria: CompCriteria) -> list[float]:
    """The sweep of radii from start to cap (inclusive), in step increments."""
    out, r = [], criteria.radius_start_miles
    while r < criteria.radius_cap_miles + 1e-9:
        out.append(round(min(r, criteria.radius_cap_miles), 4))
        r += criteria.radius_step_miles
    if out[-1] < criteria.radius_cap_miles - 1e-9:
        out.append(criteria.radius_cap_miles)
    return out


def _resolve_tier(cand: list[dict], allowed: set[str], criteria: CompCriteria):
    """Sweep radius for a fixed class set. Return (radius, comps_within) once the set
    reaches the minimum, else None. Distance is relaxed within the tier before the
    caller adds the next class."""
    pool = [c for c in cand if c["bldg_class"] in allowed]
    for r in _radii(criteria):
        within = [c for c in pool if c["distance_miles"] <= r + 1e-9]
        if len(within) >= criteria.min_comp_count:
            return r, within
    return None


def select_comps(
    con: duckdb.DuckDBPyConnection,
    subject_bbl: str,
    juris: Jurisdiction,
    criteria: CompCriteria,
    comp_table: str = "parcels",
) -> CompSet:
    crit_summary = {
        "sf_band": criteria.sf_band,
        "location_mode": criteria.location_mode,
        "radius_start_miles": criteria.radius_start_miles,
        "radius_cap_miles": criteria.radius_cap_miles,
        "radius_step_miles": criteria.radius_step_miles,
        "min_comp_count": criteria.min_comp_count,
        "exclude_condo_unit_lots": criteria.exclude_condo_unit_lots,
        "fallback": "distance-first tiered class fallback",
    }

    # --- fetch the subject ---
    subj_rows = _rows_to_dicts(
        con.execute(f"SELECT * FROM {comp_table} WHERE parcel_id = ?", [subject_bbl])
    )
    if not subj_rows:
        return _refusal(subject_bbl, None, crit_summary, "subject_not_found")
    subj = subj_rows[0]
    subj_class = subj.get("bldg_class")

    bucket = juris.product_bucket(subj_class, criteria)
    subject_summary = {
        "parcel_id": subj["parcel_id"],
        "bldg_class": subj_class,
        "bucket": bucket,
        "bucket_label": juris.product_bucket_label(bucket, criteria),
        "borough": juris.borough_of(subj["parcel_id"]),
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
        # subject's own signal values (NEVER entered into its own distribution; used
        # only to place the subject's percentile against the comps)
        "curmkttot": subj.get("curmkttot"),
        "curtxbtot": subj.get("curtxbtot"),
        "curtrntot": subj.get("curtrntot"),
        "curacttot": subj.get("curacttot"),
        "pytrntot": subj.get("pytrntot"),   # prior-year transitional (py snapshot) for realized YoY
        "roll_year": subj.get("roll_year"),  # year label for the realized transitional series
    }

    # --- scope: v1 activated product is office only ---
    if not juris.is_activated_product(subj_class, criteria):
        return _refusal(subject_bbl, subject_summary, crit_summary, "out_of_scope_v1")

    # --- a tax-exempt subject (no positive market value) has nothing to compare ---
    if criteria.exclude_non_positive_market_value and not (subj.get("curmkttot") and subj["curmkttot"] > 0):
        return _refusal(subject_bbl, subject_summary, crit_summary, "subject_tax_exempt")

    # The subject anchors the distance origin (required) and, when it has a reported
    # gross building area, the SF band. A subject with NO gross SF is NOT refused
    # wholesale (locked per-signal philosophy): it still gets a class+location comp set
    # so the assessed-value and tax-bill signals compute; only the $/SF signal refuses
    # downstream. The SF band is simply not applied.
    if subj.get("pluto_latitude") is None or subj.get("pluto_longitude") is None:
        return _refusal(subject_bbl, subject_summary, crit_summary, "subject_no_coordinates")
    sf_band_applied = bool(criteria.sf_required and subj.get("sf"))

    # --- class tiers: exact set first, then the ladder (distance relaxed before class) ---
    exact_classes = juris.exact_classes(subj_class, criteria)       # [O1] or [O5,O6]
    ladder = juris.adjacent_ladder(subj_class, criteria)            # [O2,O3] or []
    all_classes = exact_classes + ladder

    # --- candidate pull: every class that could be needed, SF band, non-condo, coords ---
    where = [
        "parcel_id != ?",
        "pluto_latitude IS NOT NULL AND pluto_longitude IS NOT NULL",
        "sf IS NOT NULL",
        f"bldg_class IN ({','.join(['?'] * len(all_classes))})",
    ]
    params: list = [subject_bbl, *all_classes]

    if sf_band_applied:
        lo = subj["sf"] * (1 - criteria.sf_band)
        hi = subj["sf"] * (1 + criteria.sf_band)
        where.append("sf BETWEEN ? AND ?")
        params += [lo, hi]

    condo_sql, condo_params = juris.condo_clause(criteria)
    where.append(condo_sql)
    params += condo_params

    # Tax-exempt parcels (curmkttot <= 0) are not assessment peers — never a comp.
    if criteria.exclude_non_positive_market_value:
        where.append("curmkttot > 0")

    if criteria.zip_prefilter:
        where.append("zip_code = ?")
        params.append(subj.get("zip_code"))

    slat, slon = subj["pluto_latitude"], subj["pluto_longitude"]
    haversine = (
        f"{EARTH_RADIUS_MI} * 2 * asin(sqrt("
        "power(sin(radians(pluto_latitude - ?) / 2), 2) + "
        "cos(radians(?)) * cos(radians(pluto_latitude)) * "
        "power(sin(radians(pluto_longitude - ?) / 2), 2)))"
    )
    sql = f"""
        WITH cand AS (
            SELECT parcel_id, source_dataset, dataset_version, roll_year, retrieval_date,
                   bldg_class, zip_code, sf, sf_source, pluto_dataset_version, year_built,
                   house_number, street_name, pluto_address, pluto_numfloors,
                   pluto_latitude, pluto_longitude, curmkttot, curtxbtot,
                   curtrntot, curacttot,
                   {haversine} AS distance_miles
            FROM {comp_table}
            WHERE {' AND '.join(where)}
        )
        SELECT * FROM cand
        WHERE distance_miles <= ?
        ORDER BY distance_miles
    """
    cand = _rows_to_dicts(con.execute(sql, [slat, slat, slon, *params, criteria.radius_cap_miles]))

    exact_set = set(exact_classes)

    # Tier 1: EXACT class only, exhausted across the full radius first.
    hit = _resolve_tier(cand, exact_set, criteria)
    fallback_triggered = False
    used_adjacent: set[str] = set()

    # Tier 2..n: add ladder classes one at a time, each swept 0.5->cap, only if exact failed.
    if hit is None and ladder:
        for i in range(len(ladder)):
            adj = set(ladder[: i + 1])
            hit = _resolve_tier(cand, exact_set | adj, criteria)
            if hit is not None:
                fallback_triggered = True
                used_adjacent = adj
                break

    if hit is None:
        return CompSet(
            subject_bbl, subject_summary, [], 0, criteria.radius_cap_miles, True,
            crit_summary, note="insufficient_comps_within_cap",
            candidates_within_cap=len(cand), sf_band_applied=sf_band_applied,
        )

    radius_used, chosen = hit
    comps = [_to_comprow(c, juris, criteria, exact_set) for c in chosen]
    exact_n = sum(1 for c in comps if c.match_type == "exact")
    adj_rows = [c for c in comps if c.match_type == "adjacent"]
    breakdown: dict = {}
    for c in adj_rows:
        breakdown[c.bldg_class] = breakdown.get(c.bldg_class, 0) + 1
    return CompSet(
        subject_bbl, subject_summary, comps, len(comps), radius_used, False,
        crit_summary, candidates_within_cap=len(cand),
        fallback_triggered=fallback_triggered, exact_count=exact_n,
        adjacent_count=len(adj_rows), adjacent_breakdown=breakdown,
        sf_band_applied=sf_band_applied,
    )


def _to_comprow(c: dict, juris: Jurisdiction, criteria: CompCriteria,
                exact_set: set[str]) -> CompRow:
    rd = c["retrieval_date"]
    citation = Citation(
        source_dataset=c["source_dataset"],
        dataset_version=c["dataset_version"],
        roll_year=c["roll_year"],
        retrieval_date=rd if isinstance(rd, date) else date.fromisoformat(str(rd)),
        parcel_id=c["parcel_id"],
    )
    return CompRow(
        citation=citation,
        bldg_class=c.get("bldg_class"),
        bucket=juris.product_bucket(c.get("bldg_class"), criteria),
        match_type="exact" if c.get("bldg_class") in exact_set else "adjacent",
        sf=c["sf"],
        sf_source=c["sf_source"],
        sf_dataset_version=c.get("pluto_dataset_version"),
        year_built=c.get("year_built"),
        house_number=c.get("house_number"),
        street_name=c.get("street_name"),
        pluto_address=c.get("pluto_address"),
        stories=c.get("pluto_numfloors"),
        distance_miles=round(c["distance_miles"], 4),
        latitude=c["pluto_latitude"],
        longitude=c["pluto_longitude"],
        curmkttot=c.get("curmkttot"),
        curtxbtot=c.get("curtxbtot"),
        curtrntot=c.get("curtrntot"),
        curacttot=c.get("curacttot"),
    )


# --------------------------------------------------------------------------- #
def _print_compset(cs: CompSet, sample: int = 5) -> None:
    s = cs.subject
    print(f"\n=== Subject {cs.subject_bbl} ===")
    if s is None:
        print(f"  (not found)  note={cs.note}")
        return
    print(f"  class {s['bldg_class']} -> bucket '{s['bucket']}' ({s['bucket_label']})")
    print(f"  {s['borough']}  ZIP {s['zip_code']}  gross SF {s['sf']}  ({s['sf_source']})")
    if cs.note in ("out_of_scope_v1", "subject_no_gross_sf", "subject_no_coordinates"):
        print(f"  REFUSED: {cs.note}")
        return
    print(f"  candidates within {cs.criteria['radius_cap_miles']} mi cap: {cs.candidates_within_cap}")
    if cs.refused:
        print(f"  REFUSED: {cs.note} (only {cs.candidates_within_cap} < "
              f"{cs.criteria['min_comp_count']} within {cs.criteria['radius_cap_miles']} mi)")
        return
    print(f"  >>> {cs.composition_label()}")
    for c in cs.comps[:sample]:
        print(f"      {c.citation.parcel_id}  {c.bldg_class:>3}  [{c.match_type:>8}]  "
              f"{c.distance_miles:>5.2f} mi  SF {c.sf:>10,.0f}  ({c.sf_source})")
    if cs.count > sample:
        print(f"      ... {cs.count - sample} more")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Select office comps for subject BBL(s) (no stats).")
    ap.add_argument("bbls", nargs="+", help="subject BBL(s), e.g. 1002230035")
    ap.add_argument("--sample", type=int, default=5, help="comp rows to print per subject")
    args = ap.parse_args(argv)

    criteria = CompCriteria.load()
    juris = get_jurisdiction(criteria.jurisdiction)
    if not config.DB_PATH.exists():
        sys.exit("screener.duckdb not found. Run the loader + pluto join first.")
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    try:
        for bbl in args.bbls:
            _print_compset(select_comps(con, bbl, juris, criteria), sample=args.sample)
    finally:
        con.close()


if __name__ == "__main__":
    main()
