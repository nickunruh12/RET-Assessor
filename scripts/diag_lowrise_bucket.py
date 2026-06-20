#!/usr/bin/env python3
"""DIAGNOSTIC ONLY — does not change any locked decision or the config file.

Compares the locked exact office bucketing (O1,O2,O3,O4 each exact) against an
alternative where O1+O2+O3 collapse into one "low-rise office" bucket (O4 stays
separate; O5+O6 and O7+O8+O9 unchanged). The alternative buckets are built in memory
via model_copy; config/comp_criteria.json is untouched.

Reports, split by borough:
  - refusal rate under exact vs under the low-rise grouping
And for a handful of formerly-refusing Bronx/Queens O1 subjects, prints the comp set
the grouped version produces, to eyeball peer reasonableness.

    PYTHONPATH=src python scripts/diag_lowrise_bucket.py
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import duckdb  # noqa: E402

from screener import config  # noqa: E402
from screener.comps import select_comps  # noqa: E402
from screener.jurisdiction import CompCriteria, get_jurisdiction  # noqa: E402


def lowrise_variant(crit: CompCriteria) -> CompCriteria:
    buckets = dict(crit.office_buckets)
    for c in ("O1", "O2", "O3"):
        buckets[c] = "O1_O2_O3"
    labels = dict(crit.office_bucket_labels)
    labels["O1_O2_O3"] = "Low-rise office (O1/O2/O3)"
    return crit.model_copy(update={"office_buckets": buckets, "office_bucket_labels": labels})


def main():
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    exact = CompCriteria.load()
    grouped = lowrise_variant(exact)
    juris = get_jurisdiction(exact.jurisdiction)

    subjects = [r[0] for r in con.execute(
        """
        SELECT parcel_id FROM parcels
        WHERE bldg_class LIKE 'O%' AND sf IS NOT NULL
          AND bldg_class NOT LIKE 'R%' AND TRY_CAST(substr(parcel_id,7,4) AS INTEGER) < 1001
          AND pluto_latitude IS NOT NULL AND pluto_longitude IS NOT NULL
        ORDER BY parcel_id
        """
    ).fetchall()]

    rec = []
    for bbl in subjects:
        ce = select_comps(con, bbl, juris, exact)
        cg = select_comps(con, bbl, juris, grouped)
        rec.append({
            "bbl": bbl, "borough": ce.subject["borough"], "class": ce.subject["bldg_class"],
            "exact_refused": ce.refused, "exact_count": ce.count,
            "grouped_refused": cg.refused, "grouped_count": cg.count,
            "grouped_radius": cg.radius_used_miles,
        })

    # ---- refusal rate by borough: exact vs grouped (low-rise buckets only affected) ----
    print("=" * 78)
    print("REFUSAL RATE by borough — EXACT vs LOW-RISE grouping (O1+O2+O3 combined)")
    print("  (only O1/O2/O3 subjects change; O4 / O5_O6 / O7_O9 identical under both)")
    print("=" * 78)
    print(f"  {'borough':14s} {'subjects':>9} {'exact ref%':>11} {'grouped ref%':>13} {'delta':>8}")
    for boro in sorted({r["borough"] for r in rec}):
        br = [r for r in rec if r["borough"] == boro]
        er = sum(1 for r in br if r["exact_refused"]) / len(br)
        gr = sum(1 for r in br if r["grouped_refused"]) / len(br)
        print(f"  {boro:14s} {len(br):>9,} {er:>10.1%} {gr:>12.1%} {gr-er:>+8.1%}")
    er = sum(1 for r in rec if r["exact_refused"]) / len(rec)
    gr = sum(1 for r in rec if r["grouped_refused"]) / len(rec)
    print(f"  {'ALL':14s} {len(rec):>9,} {er:>10.1%} {gr:>12.1%} {gr-er:>+8.1%}")

    # ---- same, restricted to the O1/O2/O3 subjects that the change actually touches ----
    print("\n" + "=" * 78)
    print("REFUSAL RATE among O1/O2/O3 subjects ONLY (the group the change affects)")
    print("=" * 78)
    print(f"  {'borough':14s} {'O1O2O3 subj':>12} {'exact ref%':>11} {'grouped ref%':>13} {'delta':>8}")
    low = [r for r in rec if r["class"] in ("O1", "O2", "O3")]
    for boro in sorted({r["borough"] for r in low}):
        br = [r for r in low if r["borough"] == boro]
        er = sum(1 for r in br if r["exact_refused"]) / len(br)
        gr = sum(1 for r in br if r["grouped_refused"]) / len(br)
        print(f"  {boro:14s} {len(br):>12,} {er:>10.1%} {gr:>12.1%} {gr-er:>+8.1%}")
    er = sum(1 for r in low if r["exact_refused"]) / len(low)
    gr = sum(1 for r in low if r["grouped_refused"]) / len(low)
    print(f"  {'ALL O1O2O3':14s} {len(low):>12,} {er:>10.1%} {gr:>12.1%} {gr-er:>+8.1%}")

    # how many formerly-refusing subjects are 'rescued' by the grouping
    rescued = [r for r in rec if r["exact_refused"] and not r["grouped_refused"]]
    print(f"\n  formerly-refusing subjects rescued by low-rise grouping: {len(rescued):,}")
    print(f"  still refusing even when grouped: {sum(1 for r in rec if r['grouped_refused']):,}")

    # ---- eyeball: a handful of formerly-refusing Bronx/Queens O1 subjects ----
    print("\n" + "=" * 78)
    print("EYEBALL — formerly-refusing Bronx/Queens O1 subjects, comp set under GROUPING")
    print("=" * 78)
    picks = [r for r in rec
             if r["class"] == "O1" and r["borough"] in ("Bronx", "Queens")
             and r["exact_refused"] and not r["grouped_refused"]][:4]
    for r in picks:
        cg = select_comps(con, r["bbl"], juris, grouped)
        s = cg.subject
        print(f"\n  Subject {r['bbl']}  {s['bldg_class']}  {s['borough']}  ZIP {s['zip_code']}  "
              f"SF {s['sf']:,.0f}")
        print(f"    exact: REFUSED ({r['exact_count']} within cap)  ->  grouped: "
              f"{cg.count} comps at {cg.radius_used_miles} mi")
        mix = collections.Counter(c.bldg_class for c in cg.comps)
        print(f"    comp class mix: {dict(mix)}")
        for c in cg.comps[:8]:
            print(f"      {c.citation.parcel_id}  {c.bldg_class:>3}  {c.distance_miles:>5.2f} mi  "
                  f"SF {c.sf:>9,.0f}  mkt {c.curmkttot:>12,.0f}")
        if cg.count > 8:
            print(f"      ... {cg.count - 8} more")
    con.close()


if __name__ == "__main__":
    main()
