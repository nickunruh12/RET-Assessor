"""Comp-selection engine — jurisdiction-agnostic. NO statistics.

Given a subject BBL, returns the set of comparable parcels and a count. It does the
generic work — fetch the subject, apply the gross-SF band, exclude the subject,
carry provenance — and delegates jurisdiction-specific predicates (class grouping,
location, condo exclusion) to a `Jurisdiction` plugin.

This module computes NOTHING statistical: no mean, median, percentile, ranking.
It only selects rows. Every comp row is constructed as a `CompRow`, which subclasses
`CitedRow`, so a comp without its provenance tuple cannot exist.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date

import duckdb

from . import config
from .jurisdiction import CompCriteria, Jurisdiction, get_jurisdiction
from .schema import Citation, CitedRow


class CompRow(CitedRow):
    """One comparable parcel. Carries the citation tuple (via CitedRow) + comp fields.

    The gross-SF value also cites its own source: `sf_source` + `sf_dataset_version`
    (PLUTO version when sf came from BldgArea), honoring the $/SF output contract.
    """

    bldg_class: str | None
    zip_code: str | None
    borough: str
    class_group: str | None
    sf: float
    sf_source: str
    sf_dataset_version: str | None
    curmkttot: float | None
    curtxbtot: float | None


@dataclass
class CompSet:
    subject_bbl: str
    subject: dict | None        # subject summary (group, borough, zip, sf, ...)
    comps: list[CompRow]
    count: int
    criteria: dict              # the criteria actually applied (for the audit trail)
    note: str | None = None     # e.g. subject_not_found, subject_no_gross_sf


# --------------------------------------------------------------------------- #
def _row_to_dict(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def select_comps(
    con: duckdb.DuckDBPyConnection,
    subject_bbl: str,
    juris: Jurisdiction,
    criteria: CompCriteria,
    comp_table: str = "parcels",
) -> CompSet:
    crit_summary = {
        "sf_band": criteria.sf_band,
        "class_match_level": criteria.class_match_level,
        "location_match": criteria.location_match,
        "exclude_condo_unit_lots": criteria.exclude_condo_unit_lots,
        "sf_required": criteria.sf_required,
    }

    # --- fetch the subject ---
    subj_rows = _row_to_dict(
        con.execute(f"SELECT * FROM {comp_table} WHERE parcel_id = ?", [subject_bbl])
    )
    if not subj_rows:
        return CompSet(subject_bbl, None, [], 0, crit_summary, note="subject_not_found")
    subj = subj_rows[0]

    subj_group = juris.class_group(subj.get("bldg_class"), criteria)
    subject_summary = {
        "parcel_id": subj["parcel_id"],
        "bldg_class": subj.get("bldg_class"),
        "class_group": subj_group,
        "class_group_label": juris.class_group_label(subj_group, criteria),
        "borough": juris.borough_of(subj["parcel_id"]),
        "zip_code": subj.get("zip_code"),
        "sf": subj.get("sf"),
        "sf_source": subj.get("sf_source"),
    }

    # The subject must have a gross-SF to anchor the band when SF is part of the match.
    if criteria.sf_required and not subj.get("sf"):
        return CompSet(subject_bbl, subject_summary, [], 0, crit_summary,
                       note="subject_no_gross_sf")

    # --- build the comp filter ---
    where = ["parcel_id != ?"]
    params: list = [subject_bbl]

    if subj_group is not None:
        where.append(f"{juris.class_group_sql('bldg_class', criteria)} = ?")
        params.append(subj_group)

    if criteria.sf_required:
        lo = subj["sf"] * (1 - criteria.sf_band)
        hi = subj["sf"] * (1 + criteria.sf_band)
        where.append("sf IS NOT NULL AND sf BETWEEN ? AND ?")
        params += [lo, hi]

    loc_sql, loc_params = juris.location_clause(subj, criteria)
    where.append(loc_sql)
    params += loc_params

    condo_sql, condo_params = juris.condo_clause(criteria)
    where.append(condo_sql)
    params += condo_params

    sql = f"""
        SELECT parcel_id, source_dataset, dataset_version, roll_year, retrieval_date,
               bldg_class, zip_code, sf, sf_source, pluto_dataset_version,
               curmkttot, curtxbtot
        FROM {comp_table}
        WHERE {' AND '.join(where)}
        ORDER BY parcel_id
    """
    rows = _row_to_dict(con.execute(sql, params))

    comps: list[CompRow] = []
    for r in rows:
        citation = Citation(
            source_dataset=r["source_dataset"],
            dataset_version=r["dataset_version"],
            roll_year=r["roll_year"],
            retrieval_date=r["retrieval_date"] if isinstance(r["retrieval_date"], date)
            else date.fromisoformat(str(r["retrieval_date"])),
            parcel_id=r["parcel_id"],
        )
        grp = juris.class_group(r.get("bldg_class"), criteria)
        comps.append(
            CompRow(
                citation=citation,
                bldg_class=r.get("bldg_class"),
                zip_code=r.get("zip_code"),
                borough=juris.borough_of(r["parcel_id"]),
                class_group=grp,
                sf=r["sf"],
                sf_source=r["sf_source"],
                sf_dataset_version=r.get("pluto_dataset_version"),
                curmkttot=r.get("curmkttot"),
                curtxbtot=r.get("curtxbtot"),
            )
        )

    return CompSet(subject_bbl, subject_summary, comps, len(comps), crit_summary)


# --------------------------------------------------------------------------- #
def _print_compset(cs: CompSet, sample: int = 5) -> None:
    s = cs.subject
    print(f"\n=== Subject {cs.subject_bbl} ===")
    if s is None:
        print(f"  (not found)  note={cs.note}")
        return
    print(f"  class {s['bldg_class']} -> group '{s['class_group']}' ({s['class_group_label']})")
    print(f"  {s['borough']}  ZIP {s['zip_code']}  gross SF {s['sf']}  ({s['sf_source']})")
    print(f"  criteria: {cs.criteria}")
    if cs.note:
        print(f"  NOTE: {cs.note}")
    print(f"  >>> COMP COUNT: {cs.count}")
    for c in cs.comps[:sample]:
        print(f"      {c.citation.parcel_id}  {c.bldg_class:>3}  ZIP {c.zip_code}  "
              f"SF {c.sf:>10,.0f}  ({c.sf_source})  src={c.citation.source_dataset}@{c.citation.roll_year}")
    if cs.count > sample:
        print(f"      ... {cs.count - sample} more")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Select comps for one or more subject BBLs (no stats).")
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
