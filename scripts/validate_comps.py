#!/usr/bin/env python3
"""Comp-selector validation report (office / distance / radius-first model).

Runs select_comps over EVERY office subject (full census, not a sample) and reports:
  (a) distribution of comp-set sizes (successes)
  (b) distribution of radius-used (0.5 suffices vs expansion vs refuse)
  (c) refusal rate (overall, by borough, by bucket)
  (d) parcel count per office class and per bucket (confirm the bucketing holds)

This is validation OF the selector, not a product stats function — summary
statistics live here in scripts/, never in the engine. No rendering, no percentiles
in the product path.

    PYTHONPATH=src python scripts/validate_comps.py
"""
from __future__ import annotations

import collections
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import duckdb  # noqa: E402

from screener import config  # noqa: E402
from screener.comps import select_comps  # noqa: E402
from screener.jurisdiction import CompCriteria, get_jurisdiction  # noqa: E402


def pctl(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    i = min(len(s) - 1, int(p * len(s)))
    return s[i]


def main():
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    crit = CompCriteria.load()
    juris = get_jurisdiction(crit.jurisdiction)

    # (d) parcel count per office class and per bucket (the comp universe)
    print("=" * 70)
    print("(d) OFFICE PARCEL COUNTS — universe = office, SF-eligible, non-condo, has coords")
    print("=" * 70)
    universe = con.execute(
        """
        SELECT bldg_class, count(*) n
        FROM parcels
        WHERE bldg_class LIKE 'O%' AND sf IS NOT NULL
          AND bldg_class NOT LIKE 'R%' AND TRY_CAST(substr(parcel_id,7,4) AS INTEGER) < 1001
          AND pluto_latitude IS NOT NULL AND pluto_longitude IS NOT NULL
        GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    by_bucket = collections.Counter()
    for cls, n in universe:
        bucket = juris.product_bucket(cls, crit)
        by_bucket[bucket] += n
        print(f"  class {cls}: {n:>6,}   -> bucket {bucket} ({juris.product_bucket_label(bucket, crit)})")
    print("  --- per bucket ---")
    for b, n in sorted(by_bucket.items()):
        print(f"  bucket {b:6s}: {n:>6,}   ({juris.product_bucket_label(b, crit)})")
    total_universe = sum(n for _, n in universe)
    print(f"  TOTAL office universe: {total_universe:,}")

    # Run the selector over every office subject.
    subjects = [r[0] for r in con.execute(
        """
        SELECT parcel_id FROM parcels
        WHERE bldg_class LIKE 'O%' AND sf IS NOT NULL
          AND bldg_class NOT LIKE 'R%' AND TRY_CAST(substr(parcel_id,7,4) AS INTEGER) < 1001
          AND pluto_latitude IS NOT NULL AND pluto_longitude IS NOT NULL
        ORDER BY parcel_id
        """
    ).fetchall()]

    rows = []
    for bbl in subjects:
        cs = select_comps(con, bbl, juris, crit)
        rows.append({
            "bbl": bbl,
            "borough": cs.subject["borough"],
            "bucket": cs.subject["bucket"],
            "refused": cs.refused,
            "note": cs.note,
            "radius": cs.radius_used_miles,
            "count": cs.count,
            "within_cap": cs.candidates_within_cap,
        })

    n = len(rows)
    succ = [r for r in rows if not r["refused"]]
    ref = [r for r in rows if r["refused"]]

    print("\n" + "=" * 70)
    print(f"Ran selector over ALL {n:,} office subjects")
    print("=" * 70)

    # (c) refusal rate
    print("\n(c) REFUSAL RATE")
    print(f"  overall: {len(ref):,}/{n:,} = {len(ref)/n:.1%} refused; {len(succ)/n:.1%} return a comp set")
    reasons = collections.Counter(r["note"] for r in ref)
    for reason, c in reasons.most_common():
        print(f"    refusal reason '{reason}': {c:,}")
    print("  by borough:")
    boros = collections.Counter(r["borough"] for r in rows)
    for boro in sorted(boros):
        br = [r for r in rows if r["borough"] == boro]
        rr = sum(1 for r in br if r["refused"])
        print(f"    {boro:14s}: {len(br):>5,} subjects, {rr/len(br):>5.1%} refused")
    print("  by bucket:")
    for bucket in sorted({r["bucket"] for r in rows}):
        br = [r for r in rows if r["bucket"] == bucket]
        rr = sum(1 for r in br if r["refused"])
        print(f"    {bucket:6s}: {len(br):>5,} subjects, {rr/len(br):>5.1%} refused")

    # (b) radius-used distribution
    print("\n(b) RADIUS-USED DISTRIBUTION")
    at_start = sum(1 for r in succ if r["radius"] <= crit.radius_start_miles + 1e-9)
    expanded = sum(1 for r in succ if r["radius"] > crit.radius_start_miles + 1e-9)
    print(f"  succeeded at {crit.radius_start_miles} mi (no expansion): {at_start:,}  ({at_start/n:.1%} of all)")
    print(f"  succeeded only after expansion (> {crit.radius_start_miles}, <= {crit.radius_cap_miles} mi): {expanded:,}  ({expanded/n:.1%})")
    print(f"  refused at {crit.radius_cap_miles} mi cap: {len(ref):,}  ({len(ref)/n:.1%})")
    print("  radius-used histogram (successes):")
    radhist = collections.Counter(r["radius"] for r in succ)
    for rad in sorted(radhist):
        print(f"    {rad:>4} mi: {radhist[rad]:>5,}")

    # (a) comp-set size distribution (successes)
    print("\n(a) COMP-SET SIZE DISTRIBUTION (successful subjects)")
    sizes = [r["count"] for r in succ]
    if sizes:
        print(f"  n={len(sizes):,}  min={min(sizes)}  p10={pctl(sizes,.10)}  p25={pctl(sizes,.25)}  "
              f"median={int(statistics.median(sizes))}  p75={pctl(sizes,.75)}  p90={pctl(sizes,.90)}  max={max(sizes)}")
        bands = [(8, 15), (15, 30), (30, 60), (60, 120), (120, 10**9)]
        print("  size bands:")
        for lo, hi in bands:
            c = sum(1 for s in sizes if lo <= s < hi)
            label = f"{lo}-{hi-1}" if hi < 10**9 else f"{lo}+"
            print(f"    {label:>8}: {c:>5,}")
    con.close()


if __name__ == "__main__":
    main()
