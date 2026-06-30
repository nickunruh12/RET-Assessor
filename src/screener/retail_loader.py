"""Persist the retail (K) classification for every class-4 K parcel into `retail_class`.

Stage 2 needs to pull SAME-CATEGORY comps, and the category is a MEASURED PLUTO floor-area
classification (Stage 1 retail.classify_retail), not the K-code. The parcels table only
carries total gross SF, so this loader fetches the PLUTO area breakdown for K lots, runs the
Stage-1 classifier on each, and writes one row per BBL: category, retail_share, per_sf_shown,
note, + PLUTO provenance. Read by the retail comp selector to filter candidates by category.

Discipline mirrors the other loaders: raw lands untouched in raw/, the typed table carries
the PLUTO source + version (the classification is PLUTO-derived). No LLM, no verdicts.

Run:
    python -m screener.retail_loader              # fetch + classify + load
    python -m screener.retail_loader --skip-fetch # rebuild table from existing raw/
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import duckdb
import httpx

from . import config
from .loader import PAGE_SIZE, dataset_version
from .retail import classify_retail

RAW_RETAIL_DIR = config.RAW_DIR / "retail_pluto"
TABLE = "retail_class"
COLS = "bbl,bldgclass,bldgarea,retailarea,officearea,resarea"


def _token_headers() -> dict[str, str]:
    tok = os.environ.get("NYC_APP_TOKEN", "")
    return {"X-App-Token": tok} if tok else {}


def fetch_pluto_k() -> dict:
    """Pull PLUTO floor-area fields for K (retail) lots verbatim to raw/."""
    RAW_RETAIL_DIR.mkdir(parents=True, exist_ok=True)
    url = config.SODA_BASE.format(dataset=config.PLUTO_DATASET)
    retrieval = date.today()
    with httpx.Client(headers=_token_headers()) as client:
        version = dataset_version(client, config.PLUTO_DATASET)
        rows, offset, page = [], 0, 0
        while True:
            recs = client.get(url, params={"$select": COLS, "$where": "bldgclass like 'K%'",
                                           "$limit": PAGE_SIZE, "$offset": offset}, timeout=300).json()
            if not recs:
                break
            (RAW_RETAIL_DIR / f"page_{page:05d}.jsonl").write_text(
                "\n".join(json.dumps(r, separators=(",", ":")) for r in recs))
            rows += recs
            page += 1
            offset += PAGE_SIZE
            if len(recs) < PAGE_SIZE:
                break
    manifest = {"source_dataset": config.PLUTO_DATASET, "dataset_version": version,
                "retrieval_date": retrieval.isoformat(), "where": "bldgclass like 'K%'",
                "row_count": len(rows), "page_count": page, "page_glob": "page_*.jsonl"}
    (RAW_RETAIL_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"  pulled {len(rows):,} PLUTO K lots -> {RAW_RETAIL_DIR}")
    return manifest


def load_manifest() -> dict:
    p = RAW_RETAIL_DIR / "manifest.json"
    if not p.exists():
        sys.exit(f"No retail-PLUTO manifest at {p}. Run a fetch first (omit --skip-fetch).")
    return json.loads(p.read_text())


def _i(v):
    try:
        return int(str(v).strip()) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def load_to_duckdb(manifest: dict, db_path: Path | None = None) -> dict:
    """Classify every class-4 K parcel (Stage-1 classifier) and persist `retail_class`."""
    db_path = db_path or config.DB_PATH
    glob = str(RAW_RETAIL_DIR / manifest["page_glob"])
    version = manifest["dataset_version"]
    con = duckdb.connect(str(db_path))
    try:
        # area breakdown per BBL (latest by bbl is unique in PLUTO); keep only class-4 K parcels.
        rows = con.execute(f"""
            SELECT p.parcel_id, p.bldg_class,
                   CAST(j.bldgarea AS VARCHAR), CAST(j.retailarea AS VARCHAR),
                   CAST(j.officearea AS VARCHAR), CAST(j.resarea AS VARCHAR)
            FROM read_json_auto('{glob}', union_by_name=true) j
            JOIN parcels p ON TRY_CAST(p.parcel_id AS BIGINT) = CAST(j.bbl AS BIGINT)
            WHERE p.bldg_class LIKE 'K%'
        """).fetchall()
        con.execute(f"DROP TABLE IF EXISTS {TABLE}")
        con.execute(f"""
            CREATE TABLE {TABLE} (
                parcel_id      VARCHAR NOT NULL,
                k_code         VARCHAR,
                category       VARCHAR NOT NULL,
                retail_share   DOUBLE,
                per_sf_shown   BOOLEAN NOT NULL,
                note           VARCHAR,
                source_dataset VARCHAR NOT NULL,
                dataset_version VARCHAR NOT NULL,
                retrieval_date DATE    NOT NULL
            )""")
        out = []
        for pid, code, ba, ret, off, res in rows:
            c = classify_retail(code, _i(ba), _i(ret), _i(off), _i(res), pluto_version=version)
            out.append((pid, c.k_code, c.category, c.retail_share, c.per_sf_shown, c.note,
                        config.PLUTO_DATASET, version, manifest["retrieval_date"]))
        con.executemany(f"INSERT INTO {TABLE} VALUES (?,?,?,?,?,?,?,?,?::DATE)", out)
        n = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
        by_cat = con.execute(f"SELECT category, count(*) FROM {TABLE} GROUP BY 1 ORDER BY 2 DESC").fetchall()
    finally:
        con.close()
    print(f"  {TABLE}: {n:,} classified K parcels")
    for cat, c in by_cat:
        print(f"    {cat:<20}{c:,}")
    return {"rows": n}


# --------------------------------------------------------------------------- #
def _table_exists(con: duckdb.DuckDBPyConnection) -> bool:
    return con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
                       [TABLE]).fetchone()[0] > 0


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Classify + load retail (K) parcels.")
    ap.add_argument("--skip-fetch", action="store_true")
    args = ap.parse_args(argv)
    print(f"=== Retail classifier loader: {config.PLUTO_DATASET} (bldgclass like 'K%') ===")
    manifest = load_manifest() if args.skip_fetch else fetch_pluto_k()
    load_to_duckdb(manifest)
    print("Done.")


if __name__ == "__main__":
    main()
