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


class CompRow(CitedRow):
    """One comparable parcel. Carries the citation tuple (via CitedRow) + comp fields.

    The gross-SF value also cites its own source: `sf_source` + `sf_dataset_version`
    (PLUTO version when sf came from BldgArea), honoring the $/SF output contract.
    """

    bldg_class: str | None
    bucket: str | None
    sf: float
    sf_source: str
    sf_dataset_version: str | None
    distance_miles: float
    latitude: float
    longitude: float
    curmkttot: float | None
    curtxbtot: float | None


@dataclass
class CompSet:
    subject_bbl: str
    subject: dict | None
    comps: list[CompRow]
    count: int
    radius_used_miles: float | None
    refused: bool
    criteria: dict
    note: str | None = None     # out_of_scope_v1 / subject_not_found / subject_no_gross_sf
    candidates_within_cap: int = 0  # diagnostic: qualifying comps inside the 1-mile cap


# --------------------------------------------------------------------------- #
def _rows_to_dicts(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _refusal(subject_bbl, subject, criteria, note, cap=None) -> CompSet:
    return CompSet(subject_bbl, subject, [], 0, cap, True, criteria, note=note)


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
    }

    # --- fetch the subject ---
    subj_rows = _rows_to_dicts(
        con.execute(f"SELECT * FROM {comp_table} WHERE parcel_id = ?", [subject_bbl])
    )
    if not subj_rows:
        return _refusal(subject_bbl, None, crit_summary, "subject_not_found")
    subj = subj_rows[0]

    bucket = juris.product_bucket(subj.get("bldg_class"), criteria)
    subject_summary = {
        "parcel_id": subj["parcel_id"],
        "bldg_class": subj.get("bldg_class"),
        "bucket": bucket,
        "bucket_label": juris.product_bucket_label(bucket, criteria),
        "borough": juris.borough_of(subj["parcel_id"]),
        "zip_code": subj.get("zip_code"),
        "sf": subj.get("sf"),
        "sf_source": subj.get("sf_source"),
        "latitude": subj.get("pluto_latitude"),
        "longitude": subj.get("pluto_longitude"),
    }

    # --- scope: v1 activated product is office only ---
    if not juris.is_activated_product(subj.get("bldg_class"), criteria):
        return _refusal(subject_bbl, subject_summary, crit_summary, "out_of_scope_v1")

    # --- subject must anchor the SF band and the distance origin ---
    if criteria.sf_required and not subj.get("sf"):
        return _refusal(subject_bbl, subject_summary, crit_summary, "subject_no_gross_sf")
    if subj.get("pluto_latitude") is None or subj.get("pluto_longitude") is None:
        return _refusal(subject_bbl, subject_summary, crit_summary, "subject_no_coordinates")

    # --- candidate pull: same bucket, SF band, non-condo, has coords, within cap ---
    bucket_codes = juris.bucket_classes(bucket, criteria)
    where = [
        "parcel_id != ?",
        "pluto_latitude IS NOT NULL AND pluto_longitude IS NOT NULL",
        "sf IS NOT NULL",
        f"bldg_class IN ({','.join(['?'] * len(bucket_codes))})",
    ]
    params: list = [subject_bbl, *bucket_codes]

    if criteria.sf_required:
        lo = subj["sf"] * (1 - criteria.sf_band)
        hi = subj["sf"] * (1 + criteria.sf_band)
        where.append("sf BETWEEN ? AND ?")
        params += [lo, hi]

    condo_sql, condo_params = juris.condo_clause(criteria)
    where.append(condo_sql)
    params += condo_params

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
                   bldg_class, zip_code, sf, sf_source, pluto_dataset_version,
                   pluto_latitude, pluto_longitude, curmkttot, curtxbtot,
                   {haversine} AS distance_miles
            FROM {comp_table}
            WHERE {' AND '.join(where)}
        )
        SELECT * FROM cand
        WHERE distance_miles <= ?
        ORDER BY distance_miles
    """
    cand = _rows_to_dicts(con.execute(sql, [slat, slat, slon, *params, criteria.radius_cap_miles]))

    # --- radius-first expansion: smallest radius reaching the minimum, else refuse ---
    radius_used, refused = _resolve_radius(cand, criteria)
    chosen = [c for c in cand if c["distance_miles"] <= radius_used]

    comps = [_to_comprow(c, juris, criteria) for c in chosen]
    note = "insufficient_comps_within_cap" if refused else None
    return CompSet(
        subject_bbl, subject_summary, comps, len(comps), radius_used, refused,
        crit_summary, note=note, candidates_within_cap=len(cand),
    )


def _resolve_radius(cand: list[dict], criteria: CompCriteria) -> tuple[float, bool]:
    """Return (radius_used, refused). Expand from start to cap until min is met."""
    start, cap, step = (criteria.radius_start_miles, criteria.radius_cap_miles,
                        criteria.radius_step_miles)
    r = start
    while r < cap + 1e-9:
        n = sum(1 for c in cand if c["distance_miles"] <= r + 1e-9)
        if n >= criteria.min_comp_count:
            return round(min(r, cap), 4), False
        r += step
    # At the cap, still short.
    return cap, True


def _to_comprow(c: dict, juris: Jurisdiction, criteria: CompCriteria) -> CompRow:
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
        sf=c["sf"],
        sf_source=c["sf_source"],
        sf_dataset_version=c.get("pluto_dataset_version"),
        distance_miles=round(c["distance_miles"], 4),
        latitude=c["pluto_latitude"],
        longitude=c["pluto_longitude"],
        curmkttot=c.get("curmkttot"),
        curtxbtot=c.get("curtxbtot"),
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
    print(f"  radius used: {cs.radius_used_miles} mi")
    print(f"  >>> COMP COUNT: {cs.count}")
    for c in cs.comps[:sample]:
        print(f"      {c.citation.parcel_id}  {c.bldg_class:>3}  {c.distance_miles:>5.2f} mi  "
              f"SF {c.sf:>10,.0f}  ({c.sf_source})")
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
