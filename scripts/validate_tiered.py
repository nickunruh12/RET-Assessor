#!/usr/bin/env python3
"""Validation report for the tiered (distance-first) comp fallback — full office census.

Runs the selector over all office subjects under:
  - EXACT baseline (fallback ladder emptied in memory -> exact-or-refuse), to reproduce
    the prior 36.5% exact refusal rate as an apples-to-apples control, and
  - TIERED (the committed config with the fallback ladder live).

Reports, split by borough:
  (a) refusal rate: tiered vs exact baseline (and the 31.8% grouped diagnostic baseline)
  (b) of non-refusing subjects, share fully-exact vs needed class fallback
  (c) comp-set size distribution
Plus spot-checks 3 formerly-refusing (exact-refused) Bronx/Queens subjects with the new
comp set and its exact-vs-adjacent breakdown.

    PYTHONPATH=src python scripts/validate_tiered.py
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

GROUPED_BASELINE = 0.318  # from scripts/diag_lowrise_bucket.py (O1+O2+O3 one bucket)


def pctl(xs, p):
    s = sorted(xs)
    return s[min(len(s) - 1, int(p * len(s)))] if s else None


def main():
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    tiered = CompCriteria.load()
    exact = tiered.model_copy(update={"fallback_ladder": {}})  # exact-or-refuse control
    juris = get_jurisdiction(tiered.jurisdiction)

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
        ct = select_comps(con, bbl, juris, tiered)
        ce = select_comps(con, bbl, juris, exact)
        rows.append({
            "bbl": bbl, "borough": ct.subject["borough"], "class": ct.subject["bldg_class"],
            "t_refused": ct.refused, "t_count": ct.count, "t_fallback": ct.fallback_triggered,
            "t_radius": ct.radius_used_miles, "e_refused": ce.refused,
        })

    n = len(rows)

    # (a) refusal rate by borough: tiered vs exact baseline
    print("=" * 78)
    print("(a) REFUSAL RATE — TIERED vs EXACT baseline (grouped baseline = 31.8% overall)")
    print("=" * 78)
    print(f"  {'borough':14s} {'subj':>6} {'exact ref%':>11} {'tiered ref%':>12} {'delta vs exact':>15}")
    for boro in sorted({r["borough"] for r in rows}):
        br = [r for r in rows if r["borough"] == boro]
        er = sum(1 for r in br if r["e_refused"]) / len(br)
        tr = sum(1 for r in br if r["t_refused"]) / len(br)
        print(f"  {boro:14s} {len(br):>6,} {er:>10.1%} {tr:>11.1%} {tr-er:>+14.1%}")
    er = sum(1 for r in rows if r["e_refused"]) / n
    tr = sum(1 for r in rows if r["t_refused"]) / n
    print(f"  {'ALL':14s} {n:>6,} {er:>10.1%} {tr:>11.1%} {tr-er:>+14.1%}")
    print(f"  baselines: exact {er:.1%} (reproduces prior 36.5%), grouped {GROUPED_BASELINE:.1%}, "
          f"tiered {tr:.1%}")

    # (b) of non-refusing tiered subjects: fully-exact vs needed fallback
    print("\n" + "=" * 78)
    print("(b) AMONG NON-REFUSING (tiered): fully-exact vs needed class fallback")
    print("=" * 78)
    succ = [r for r in rows if not r["t_refused"]]
    print(f"  {'borough':14s} {'success':>8} {'fully-exact':>12} {'used fallback':>14}")
    for boro in sorted({r["borough"] for r in succ}):
        br = [r for r in succ if r["borough"] == boro]
        fb = sum(1 for r in br if r["t_fallback"])
        ex = len(br) - fb
        print(f"  {boro:14s} {len(br):>8,} {ex/len(br):>11.1%} {fb/len(br):>13.1%}")
    fb = sum(1 for r in succ if r["t_fallback"])
    print(f"  {'ALL':14s} {len(succ):>8,} {(len(succ)-fb)/len(succ):>11.1%} {fb/len(succ):>13.1%}")
    print(f"  (fully-exact = {len(succ)-fb:,}, used fallback = {fb:,} of {len(succ):,} successes)")

    # (c) comp-set size distribution (tiered successes)
    print("\n" + "=" * 78)
    print("(c) COMP-SET SIZE DISTRIBUTION (tiered successes)")
    print("=" * 78)
    sizes = [r["t_count"] for r in succ]
    print(f"  n={len(sizes):,}  min={min(sizes)}  p10={pctl(sizes,.1)}  p25={pctl(sizes,.25)}  "
          f"median={int(statistics.median(sizes))}  p75={pctl(sizes,.75)}  p90={pctl(sizes,.9)}  max={max(sizes)}")
    for lo, hi in [(8, 15), (15, 30), (30, 60), (60, 120), (120, 10**9)]:
        c = sum(1 for s in sizes if lo <= s < hi)
        print(f"    {(str(lo)+'-'+str(hi-1)) if hi<10**9 else str(lo)+'+':>8}: {c:>5,}")

    # spot-check: formerly-refusing (exact) Bronx/Queens subjects now succeeding
    print("\n" + "=" * 78)
    print("SPOT-CHECK — 3 formerly-refusing (exact) Bronx/Queens subjects, new comp set")
    print("=" * 78)
    picks = [r for r in rows
             if r["e_refused"] and not r["t_refused"]
             and r["borough"] in ("Bronx", "Queens")][:3]
    for r in picks:
        cs = select_comps(con, r["bbl"], juris, tiered)
        s = cs.subject
        print(f"\n  Subject {r['bbl']}  {s['bldg_class']}  {s['borough']}  ZIP {s['zip_code']}  "
              f"SF {s['sf']:,.0f}   (exact: REFUSED)")
        print(f"    -> {cs.composition_label()}")
        for c in cs.comps:
            print(f"       {c.citation.parcel_id}  {c.bldg_class:>3}  [{c.match_type:>8}]  "
                  f"{c.distance_miles:>5.2f} mi  SF {c.sf:>9,.0f}  mkt {c.curmkttot:>12,.0f}")
    con.close()


if __name__ == "__main__":
    main()
