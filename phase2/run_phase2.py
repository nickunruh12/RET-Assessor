#!/usr/bin/env python3
"""
Phase 2 kill-gate runner for the NYC Commercial Assessment Outlier Screener.

Runs the fill-rate, value-field, and ground-truth checks the roadmap requires
BEFORE any engine code. Self-introspecting: it fetches one row first and prints
every column so the "value-field minefield" is resolved by inspection, not guess.

Requires internet access to data.cityofnewyork.us (the build sandbox cannot reach it;
run this locally). Standard library only — no pip installs.

Optional: set a free Socrata app token to avoid throttling:
    export NYC_APP_TOKEN=your_token_here
Get one at https://data.cityofnewyork.us/profile/edit/developer_settings

Usage:
    python3 run_phase2.py
Writes results to phase2_results.json next to this script.
"""

import json, os, sys, urllib.request, urllib.parse, ssl

ROLL = "8y4t-faws"      # DOF Property Valuation & Assessment Data (classes 1-4)
PLUTO = "64uk-42ks"     # DCP PLUTO
BASE = "https://data.cityofnewyork.us/resource/{}.json"
TOKEN = os.environ.get("NYC_APP_TOKEN", "")
FILL_GATE = 0.80        # roadmap ~80% threshold
CTX = ssl.create_default_context()


def soda(dataset, params):
    url = BASE.format(dataset) + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    if TOKEN:
        req.add_header("X-App-Token", TOKEN)
    with urllib.request.urlopen(req, timeout=120, context=CTX) as r:
        return json.loads(r.read().decode())


def count(dataset, where=None):
    p = {"$select": "count(*) as n"}
    if where:
        p["$where"] = where
    return int(soda(dataset, p)[0]["n"])


def pick(cols, *cands):
    """Return the first candidate column name that exists (case-insensitive)."""
    low = {c.lower(): c for c in cols}
    for c in cands:
        if c.lower() in low:
            return low[c.lower()]
    return None


def fill(dataset, where_class, col):
    """Fraction of rows within the class filter where `col` is non-null/non-blank."""
    total = count(dataset, where_class)
    if total == 0:
        return 0, 0, 0.0
    nn_where = f"({where_class}) AND {col} IS NOT NULL AND {col} != ''" if where_class else f"{col} IS NOT NULL"
    nn = count(dataset, nn_where)
    return nn, total, (nn / total if total else 0.0)


def gate(label, rate):
    status = "PASS" if rate >= FILL_GATE else "FAIL"
    print(f"  [{status}] {label}: {rate:.1%}")
    return status


def main():
    out = {"roll_dataset": ROLL, "pluto_dataset": PLUTO, "fill_gate": FILL_GATE,
           "token_used": bool(TOKEN), "results": {}}

    # --- Step 0: introspect roll columns (resolves the value-field minefield) ---
    print("=== ROLL column introspection (8y4t-faws) ===")
    sample = soda(ROLL, {"$limit": 1})[0]
    cols = list(sample.keys())
    print("Columns:", ", ".join(cols))
    print("Sample row:", json.dumps(sample, indent=2)[:1500])
    out["roll_columns"] = cols
    out["roll_sample"] = sample

    taxcol = pick(cols, "taxclass", "tax_class", "curtaxclass", "taxclass_code")
    yearcol = pick(cols, "yearbuilt", "yrbuilt", "year_built")
    bldgcol = pick(cols, "bldgcl", "bldgclass", "building_class", "bldg_class")
    zipcol = pick(cols, "zip", "zip_code", "postcode", "zipcode")
    print(f"\nDetected -> taxclass:{taxcol}  yearbuilt:{yearcol}  bldgclass:{bldgcol}  zip:{zipcol}")
    out["detected_cols"] = {"taxclass": taxcol, "yearbuilt": yearcol,
                            "bldgclass": bldgcol, "zip": zipcol}

    value_candidates = [c for c in cols if any(k in c.lower() for k in
                        ("fullval", "mktval", "market", "avtot", "avland", "actval", "fulval"))]
    print("VALUE-FIELD CANDIDATES (lock one in DECISIONS.md):", value_candidates)
    out["value_field_candidates"] = value_candidates

    if not taxcol:
        print("\n!! Could not detect tax class column. Inspect columns above and set manually.")
        json.dump(out, open(_results_path(), "w"), indent=2)
        sys.exit(2)

    # tax class value may be '4' or '4 ' etc; detect distinct values
    classvals = soda(ROLL, {"$select": f"{taxcol}", "$group": taxcol, "$limit": 50})
    print("Distinct tax class values:", [c.get(taxcol) for c in classvals])
    c4 = "4"
    where4 = f"{taxcol}='{c4}'"

    # --- Step 1: fill rates on class 4 ---
    print("\n=== Step 1: ROLL fill rates (class 4) ===")
    res = {}
    res["class4_total"] = count(ROLL, where4)
    print(f"  class 4 parcels: {res['class4_total']:,}")
    for label, col in (("year_built", yearcol), ("building_class", bldgcol), ("zip", zipcol)):
        if not col:
            print(f"  [SKIP] {label}: column not found")
            continue
        nn, tot, rate = fill(ROLL, where4, col)
        res[f"fill_{label}"] = {"non_null": nn, "total": tot, "rate": rate,
                                "gate": gate(label, rate)}

    # --- Step 1b: PLUTO BldgArea fill on commercial classes ---
    print("\n=== Step 1b: PLUTO BldgArea fill (commercial bldg classes O*, K*) ===")
    psample = soda(PLUTO, {"$limit": 1})[0]
    pcols = list(psample.keys())
    out["pluto_columns"] = pcols
    barea = pick(pcols, "bldgarea", "bldg_area")
    bclass = pick(pcols, "bldgclass", "bldg_class")
    print(f"Detected PLUTO -> bldgarea:{barea}  bldgclass:{bclass}")
    if barea and bclass:
        comm_where = f"(starts_with({bclass}, 'O') OR starts_with({bclass}, 'K'))"
        nn, tot, rate = fill(PLUTO, comm_where, barea)
        res["pluto_bldgarea_commercial"] = {"non_null": nn, "total": tot, "rate": rate,
                                            "gate": gate("PLUTO BldgArea (commercial)", rate)}
    else:
        print("  [SKIP] PLUTO BldgArea/BldgClass column not detected")

    # --- Step 3: ground-truth sample (20 class 4 parcels for manual DOF lookup) ---
    print("\n=== Step 3: 20 class 4 parcels for manual DOF cross-check ===")
    selcols = [c for c in (pick(cols, "bble", "bbl", "parid"), taxcol, bldgcol, zipcol,
                           *value_candidates[:2]) if c]
    sample20 = soda(ROLL, {"$where": where4, "$limit": 20, "$select": ",".join(selcols)})
    for row in sample20:
        print("  ", row)
    res["ground_truth_sample"] = sample20

    out["results"] = res
    json.dump(out, open(_results_path(), "w"), indent=2)
    print(f"\nWrote {_results_path()}")
    print("\nNext: paste any FAIL into DECISIONS.md, lock the value field from the candidates above,")
    print("and confirm the 20 sample parcels match the public DOF property lookup.")


def _results_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "phase2_results.json")


if __name__ == "__main__":
    main()
