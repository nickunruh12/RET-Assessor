#!/usr/bin/env python3
"""RUNG 3 validation — fencing the one user-supplied number.

  (a) normal positive NOI on a valid subject -> single stamped line, partitioned
  (b) junk NOI (zero / negative / non-numeric) -> rejected, no cap rate computed
  (c) tax-exempt subject -> refuses to run (no division)
Plus a structural-partition proof: the RUNG 3 object shares NO fields with the public
signal / variance outputs, so a user-derived number cannot blend into a public one.

    PYTHONPATH=src python scripts/validate_rung3.py
"""
from __future__ import annotations

import sys
from dataclasses import fields
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import duckdb  # noqa: E402

from screener import config  # noqa: E402
from screener.comps import select_comps  # noqa: E402
from screener.jurisdiction import CompCriteria, get_jurisdiction  # noqa: E402
from screener.rung3 import Rung3Result, run_rung3  # noqa: E402
from screener.stats import SignalStats, StatsResult, compute_stats  # noqa: E402
from screener.variance import VarianceRow  # noqa: E402

VALID = "1000090001"       # O4 Manhattan, positive market value
TAX_EXEMPT = "1000380001"  # O4 Manhattan, curmkttot = 0


def dump(label, r: Rung3Result):
    print(f"\n--- {label} ---")
    print(f"  partition={r.partition}  enabled={r.enabled}  computed={r.computed}  "
          f"rejected={r.rejected}  reason={r.rejection_reason}")
    print(f"  stamp: {r.stamp}")
    if r.computed:
        print(f"  user_noi={r.user_noi:,.0f} (source={r.noi_source}, citation=NONE)")
        print(f"  market_value={r.market_value:,.0f}  cited_to="
              f"{r.market_value_citation['source_dataset']}@{r.market_value_citation['roll_year']}")
        print(f"  >>> {r.statement}")
    else:
        print(f"  message: {r.message}")


def main():
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    crit = CompCriteria.load()
    juris = get_jurisdiction(crit.jurisdiction)

    print("=" * 80)
    print("OFF BY DEFAULT — standard call does not run RUNG 3")
    dump("enabled omitted (default off)", run_rung3(con, VALID, 12_000_000))

    print("\n" + "=" * 80)
    print("(a) NORMAL positive NOI on a valid subject (enabled=True)")
    dump("NOI = 12,000,000", run_rung3(con, VALID, 12_000_000, enabled=True))

    print("\n" + "=" * 80)
    print("(b) JUNK NOI — rejected, no cap rate computed")
    for label, noi in [("zero", 0), ("negative", -500_000), ("non-numeric", "lots"),
                       ("empty string", ""), ("None", None)]:
        dump(f"NOI = {label!r}", run_rung3(con, VALID, noi, enabled=True))

    print("\n" + "=" * 80)
    print("(c) TAX-EXEMPT subject — refuses to run (no division)")
    dump("exempt subject, NOI = 12,000,000", run_rung3(con, TAX_EXEMPT, 12_000_000, enabled=True))

    # ---- structural partition proof ----
    print("\n" + "=" * 80)
    print("PARTITION PROOF — RUNG 3 object vs the public signal/variance outputs")
    cs = select_comps(con, VALID, juris, crit)
    stats = compute_stats(cs, crit)
    r3 = run_rung3(con, VALID, 12_000_000, enabled=True)

    r3_fields = {f.name for f in fields(Rung3Result)}
    stats_fields = {f.name for f in fields(StatsResult)}
    signal_fields = {f.name for f in fields(SignalStats)}
    variance_fields = set(VarianceRow.model_fields.keys())

    print(f"  RUNG3 result type: {type(r3).__name__}   partition tag: {r3.partition!r}")
    print(f"  StatsResult type:  {type(stats).__name__}  (has 'signals': {hasattr(stats, 'signals')}; "
          f"has 'partition': {hasattr(stats, 'partition')})")
    print(f"  RUNG3 ∩ StatsResult fields: {sorted(r3_fields & stats_fields)}")
    print(f"  RUNG3 ∩ SignalStats fields: {sorted(r3_fields & signal_fields)}")
    print(f"  RUNG3 ∩ VarianceRow fields: {sorted(r3_fields & variance_fields)}")
    print(f"  'partition' marker on any public object? "
          f"stats={hasattr(stats, 'partition')}, signal={'partition' in signal_fields}, "
          f"variance={'partition' in variance_fields}")
    blended = (r3_fields & (stats_fields | signal_fields | variance_fields)) - {"subject_bbl"}
    print(f"  shared fields beyond subject_bbl (should be empty): {sorted(blended)}")
    assert "partition" not in (stats_fields | signal_fields | variance_fields)
    assert not blended, "RUNG 3 shares structure with a public output — partition breached"
    print("  ✓ RUNG 3 is a structurally separate object; cannot blend into public signals")
    con.close()


if __name__ == "__main__":
    main()
