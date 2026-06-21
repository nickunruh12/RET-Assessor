#!/usr/bin/env python3
"""LIVE validation of the address->BBL resolver against NYC Geoclient v2.

Hits the real API (needs GEOCLIENT_API_KEY in .env). The key is read from the env and
NEVER printed. Confirms:
  * 3 ground-truth office addresses resolve to the correct BBL
  * a non-office (class-4 store) address -> out-of-scope refusal
  * a garbage address -> "address not found" (no crash, no guess)

    PYTHONPATH=src python scripts/validate_geocode.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import duckdb  # noqa: E402

from screener import config  # noqa: E402
from screener.geocode import GeoclientConfigError, get_api_key, resolve_address  # noqa: E402

GROUND_TRUTH = [
    ("438", "Greenwich Street", "Manhattan", "1002230035"),
    ("646", "East 12 Street", "Manhattan", "1003940032"),
    ("356", "West 12 Street", "Manhattan", "1006400041"),
]


def line(r, expect=None):
    tag = f"BBL={r.bbl}" if r.bbl else f"(no BBL)"
    verdict = ""
    if expect is not None:
        verdict = "  ✓" if r.bbl == expect else f"  ✗ expected {expect}"
    print(f"  ok={r.ok!s:5} refused={r.refused!s:5} reason={r.reason or '-':18} "
          f"class={r.bldg_class or '-':4} {tag}{verdict}")
    if r.message:
        print(f"      message: {r.message}")


def main():
    try:
        get_api_key()  # fail early with a clear message if the key is missing
    except GeoclientConfigError as e:
        sys.exit(str(e))

    con = duckdb.connect(str(config.DB_PATH), read_only=True)

    print("=" * 78)
    print("GROUND-TRUTH office addresses -> expected BBL")
    all_ok = True
    for hn, st, boro, expect in GROUND_TRUTH:
        r = resolve_address(hn, st, borough=boro, con=con)
        print(f"\n{hn} {st}, {boro}")
        line(r, expect)
        all_ok = all_ok and r.ok and r.bbl == expect

    # non-office class-4 parcel: pull a real store (K*) address from the roll and resolve it
    print("\n" + "=" * 78)
    print("NON-OFFICE class-4 address -> out-of-scope refusal")
    store = con.execute(
        """SELECT rr.housenum_lo, rr.street_name, rr.zip_code, rr.parid, p.bldg_class
           FROM raw_roll rr JOIN parcels p ON rr.parid = p.parcel_id
           WHERE p.bldg_class LIKE 'K%' AND rr.housenum_lo IS NOT NULL
             AND rr.street_name IS NOT NULL AND substr(rr.parid,1,1)='1'
           LIMIT 1"""
    ).fetchone()
    if store:
        hn, st, zp, bbl, cls = store
        print(f"\n{hn} {st} (zip {zp})  [roll says {bbl}, class {cls}]")
        r = resolve_address(str(hn).strip(), str(st).strip(), zip_code=str(zp).strip(), con=con)
        line(r)
        print(f"   -> refused & out-of-scope: "
              f"{r.refused and r.reason in ('out_of_scope_v1', 'not_class_4')}")

    # garbage address
    print("\n" + "=" * 78)
    print("GARBAGE address -> address not found (no crash, no guess)")
    r = resolve_address("99999", "Nonexistent Boulevard", borough="Manhattan", con=con)
    print()
    line(r)
    print(f"   -> address_not_found & no BBL: {r.reason == 'address_not_found' and r.bbl is None}")

    con.close()
    print("\n" + "=" * 78)
    print(f"GROUND-TRUTH all correct: {all_ok}")


if __name__ == "__main__":
    main()
