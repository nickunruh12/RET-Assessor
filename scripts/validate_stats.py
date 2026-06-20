#!/usr/bin/env python3
"""Stats-layer validation: full per-signal distributions for 3 subjects + a hand-check.

  1. dense Manhattan office, large comp set
  2. fallback-heavy set (1 exact + adjacent)
  3. missing gross SF -> assessed + tax-bill compute, $/SF refuses (per-signal)

Then re-derives one subject's median and percentile by hand to show the math is exact.

    PYTHONPATH=src python scripts/validate_stats.py
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import duckdb  # noqa: E402

from screener import config  # noqa: E402
from screener.comps import select_comps  # noqa: E402
from screener.jurisdiction import CompCriteria, get_jurisdiction  # noqa: E402
from screener.stats import compute_stats  # noqa: E402

DENSE = "1000090001"      # O4 Manhattan, large set
FALLBACK = "2023070046"   # O1 Bronx, 1 exact + 7 adjacent
NO_SF = "3053480042"      # O9 Brooklyn, no gross SF


def fmt(v, unit):
    if v is None:
        return "—"
    if unit == "fraction":
        return f"{v:.4f}"
    return f"{v:,.2f}"


def show(res):
    s = res.subject
    print("\n" + "=" * 80)
    print(f"SUBJECT {res.subject_bbl}  {s['bldg_class']} ({s['bucket_label']})  "
          f"{s['borough']}  ZIP {s['zip_code']}  SF {s['sf']}")
    if res.refused:
        print(f"  WHOLE-SCREEN REFUSAL: {res.note}")
        return
    comp = res.composition
    print(f"  comps: {res.comp_count}  radius {res.radius_used_miles} mi  "
          f"sf_band_applied={res.sf_band_applied}")
    print(f"  composition: {comp['exact_count']} exact, {comp['adjacent_count']} adjacent "
          f"{dict(comp['adjacent_breakdown'])}  fallback={comp['fallback_triggered']}")
    if res.low_exact_caution:
        print(f"  ⚠ CAUTION: {res.caution_message}")
    print(f"  provenance: roll {res.provenance['source_dataset']} v="
          f"{res.provenance['dataset_version']} roll_year={res.provenance['roll_year']} "
          f"retrieved {res.provenance['retrieval_date']}")
    print(f"              SF source PLUTO {res.provenance['sf_pluto_versions']}  "
          f"tax_rate={res.provenance['tax_rate_applied']}")
    for sig in res.signals.values():
        print(f"\n  [{sig.key}]  {sig.label}   unit={sig.unit}")
        if sig.refused:
            print(f"      REFUSED: {sig.refusal_reason}")
            for n in sig.notes:
                print(f"      note: {n}")
            print(f"      (excluded-blank comps for this field: {sig.excluded_blank})")
            continue
        print(f"      population: {sig.population}")
        print(f"      n={sig.n}   excluded_blank={sig.excluded_blank}")
        print(f"      mean={fmt(sig.mean, sig.unit)}  median={fmt(sig.median, sig.unit)}  "
              f"min={fmt(sig.minimum, sig.unit)}  max={fmt(sig.maximum, sig.unit)}  "
              f"stddev={fmt(sig.stddev, sig.unit)}")
        print(f"      subject_value={fmt(sig.subject_value, sig.unit)}  "
              f"subject_percentile={sig.subject_percentile}")
        for n in sig.notes:
            print(f"      note: {n}")


def hand_verify(con, juris, crit, bbl):
    print("\n" + "#" * 80)
    print(f"# HAND-VERIFICATION — subject {bbl}, assessed market value signal")
    print("#" * 80)
    cs = select_comps(con, bbl, juris, crit)
    res = compute_stats(cs, crit)
    sig = res.signals["assessed_value_market"]
    vals = sorted(c.curmkttot for c in cs.comps if c.curmkttot is not None)
    print(f"  comp curmkttot values (sorted, n={len(vals)}):")
    print("   ", [f"{v:,.0f}" for v in vals])
    # median by hand
    n = len(vals)
    if n % 2 == 1:
        manual_median = vals[n // 2]
        how = f"odd n -> middle element index {n//2}"
    else:
        manual_median = (vals[n // 2 - 1] + vals[n // 2]) / 2
        how = f"even n -> mean of indices {n//2-1},{n//2}"
    subj_val = res.subject["curmkttot"]
    below = sum(1 for v in vals if v < subj_val)
    manual_pct = round(100.0 * below / n, 2)
    print(f"  manual median  = {manual_median:,.2f}  ({how})")
    print(f"  stats  median  = {sig.median:,.2f}")
    print(f"  subject curmkttot = {subj_val:,.0f}; comps strictly below = {below} of {n}")
    print(f"  manual percentile = 100*{below}/{n} = {manual_pct}")
    print(f"  stats  percentile = {sig.subject_percentile}")
    assert abs(manual_median - sig.median) < 1e-9, "median mismatch"
    assert abs(manual_pct - sig.subject_percentile) < 1e-9, "percentile mismatch"
    # mean + population stddev by hand too
    manual_mean = sum(vals) / n
    manual_std = (sum((v - manual_mean) ** 2 for v in vals) / n) ** 0.5
    print(f"  manual mean={manual_mean:,.2f} stddev={manual_std:,.2f}  vs stats "
          f"mean={sig.mean:,.2f} stddev={sig.stddev:,.2f}")
    assert abs(manual_mean - sig.mean) < 1e-6 and abs(manual_std - sig.stddev) < 1e-6
    print("  ✓ median, percentile, mean, population stddev all match exactly")


def main():
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    crit = CompCriteria.load()
    juris = get_jurisdiction(crit.jurisdiction)
    for bbl in (DENSE, FALLBACK, NO_SF):
        show(compute_stats(select_comps(con, bbl, juris, crit), crit))
    hand_verify(con, juris, crit, FALLBACK)
    con.close()


if __name__ == "__main__":
    main()
