"""Multi-year SUBJECT transitional-taxable series for the Phase-In Note.

This is a LOADER-FILTER WIDENING, not a new data source: all years 2023–2027 live inside the
same roll dataset (8y4t-faws). To keep the canonical roll_class4 (FY2027, one row per BBL)
and its locked count completely untouched — and to avoid a multi-GB `$select=*` re-pull — the
multi-year window is fetched column-projected (only the fields the series needs) into its own
raw area, and reduced to ONE row per (BBL, roll_year).

CRITICAL period rule (must be period 3 = Final, which can differ materially from period 1 =
Tentative): this module REUSES loader.FINAL_PERIOD_ORDER — the exact same "highest period"
dedup that produces the canonical class-4 rows — partitioned per BBL-year. No second, parallel
period filter is written. Edge case: if a year's Final (period 3) is not published yet, the
same ordering naturally falls back to that year's Tentative (period 1); roll_period is carried
so the display can label it "tentative" rather than dropping the year.

Discipline: raw lands untouched in raw/; the typed table carries the full provenance tuple
(source_dataset, dataset_version, roll_year, retrieval_date, parcel_id) per row, roll_year
included — every annual value is independently traceable.

Run:
    python -m screener.taxable_series              # fetch + load
    python -m screener.taxable_series --skip-fetch # rebuild table from existing raw/
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
from .loader import FINAL_PERIOD_ORDER, PAGE_SIZE, dataset_version

RAW_SERIES_DIR = config.RAW_DIR / "roll_series"
TABLE = "roll_taxable_series"
# Verbatim column projection — the only fields the series + its dedup tiebreakers need.
SERIES_COLS = "parid,year,period,curtxbtot,curmkttot,curtaxclass,extracrdt,easement,valref"
WHERE = (f"{config.COL_TAX_CLASS}='{config.TAX_CLASS}' AND year in ("
         + ",".join(f"'{y}'" for y in config.ROLL_YEAR_WINDOW) + ")")


def _token_headers() -> dict[str, str]:
    tok = os.environ.get("NYC_APP_TOKEN", "")
    return {"X-App-Token": tok} if tok else {}


# --------------------------------------------------------------------------- #
def fetch_series(force: bool = True) -> dict:
    """Page the roll for the 2023–2027 class-4 window (projected columns) verbatim to raw/."""
    RAW_SERIES_DIR.mkdir(parents=True, exist_ok=True)
    url = config.SODA_BASE.format(dataset=config.ROLL_DATASET)
    retrieval = date.today()
    with httpx.Client(headers=_token_headers()) as client:
        version = dataset_version(client, config.ROLL_DATASET)
        print(f"  dataset_version = {version}")
        offset = page = total = 0
        while True:
            params = {"$where": WHERE, "$select": SERIES_COLS,
                      "$order": f"{config.COL_BBL},year", "$limit": PAGE_SIZE, "$offset": offset}
            recs = client.get(url, params=params, timeout=300).json()
            if not recs:
                break
            with (RAW_SERIES_DIR / f"page_{page:05d}.jsonl").open("w") as f:
                for r in recs:
                    f.write(json.dumps(r, separators=(",", ":")) + "\n")
            total += len(recs)
            print(f"  page {page}: {len(recs):,} rows (running total {total:,})")
            page += 1
            offset += PAGE_SIZE
            if len(recs) < PAGE_SIZE:
                break
    manifest = {
        "source_dataset": config.ROLL_DATASET, "dataset_version": version,
        "roll_year_window": config.ROLL_YEAR_WINDOW, "tax_class": config.TAX_CLASS,
        "retrieval_date": retrieval.isoformat(), "where": WHERE, "endpoint": url,
        "row_count": total, "page_count": page, "page_glob": "page_*.jsonl",
        "columns": SERIES_COLS,
    }
    (RAW_SERIES_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"  wrote {total:,} raw rows across {page} page file(s) -> {RAW_SERIES_DIR}")
    return manifest


def load_manifest() -> dict:
    p = RAW_SERIES_DIR / "manifest.json"
    if not p.exists():
        sys.exit(f"No series manifest at {p}. Run a fetch first (omit --skip-fetch).")
    return json.loads(p.read_text())


# --------------------------------------------------------------------------- #
def load_to_duckdb(manifest: dict, db_path: Path | None = None) -> dict:
    """Build roll_taxable_series: ONE row per (BBL, year), final-period preferred via the
    SHARED FINAL_PERIOD_ORDER (period 3 over period 1). roll_period carried for the tentative
    edge case; is_exempt distinguishes a real $0 from a missing year (missing = no row)."""
    db_path = db_path or config.DB_PATH
    glob = str(RAW_SERIES_DIR / manifest["page_glob"])
    con = duckdb.connect(str(db_path))
    try:
        con.execute(f"DROP TABLE IF EXISTS {TABLE}")
        con.execute(f"""
            CREATE TABLE {TABLE} (
                parcel_id      VARCHAR NOT NULL,
                source_dataset VARCHAR NOT NULL,
                dataset_version VARCHAR NOT NULL,
                roll_year      VARCHAR NOT NULL,
                retrieval_date DATE    NOT NULL,
                roll_period    VARCHAR,            -- '3'=Final, '1'=Tentative (edge-case fallback)
                curtxbtot      DOUBLE,             -- transitional taxable for that roll year
                curmkttot      DOUBLE,             -- to distinguish exempt ($0) from a missing year
                is_exempt      BOOLEAN             -- TRUE when the parcel-year is a real $0 (exempt)
            )""")
        con.execute(f"""
            INSERT INTO {TABLE}
            SELECT {config.COL_BBL} AS parcel_id, ? AS source_dataset, ? AS dataset_version,
                   year AS roll_year, ?::DATE AS retrieval_date, period AS roll_period,
                   TRY_CAST(curtxbtot AS DOUBLE) AS curtxbtot,
                   TRY_CAST(curmkttot AS DOUBLE) AS curmkttot,
                   (COALESCE(TRY_CAST(curtxbtot AS DOUBLE), 0) = 0
                    AND COALESCE(TRY_CAST(curmkttot AS DOUBLE), 0) = 0) AS is_exempt
            FROM read_json_auto('{glob}', union_by_name=true)
            WHERE {config.COL_BBL} IS NOT NULL AND {config.COL_BBL} != ''
              AND {config.COL_TAX_CLASS} = '{config.TAX_CLASS}'
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY {config.COL_BBL}, year
                ORDER BY {FINAL_PERIOD_ORDER}
            ) = 1
        """, [manifest["source_dataset"], manifest["dataset_version"], manifest["retrieval_date"]])
        n = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
        bbls = con.execute(f"SELECT count(DISTINCT parcel_id) FROM {TABLE}").fetchone()[0]
        by_year = con.execute(
            f"SELECT roll_year, count(*) FROM {TABLE} GROUP BY roll_year ORDER BY roll_year").fetchall()
    finally:
        con.close()
    print(f"  {TABLE}: {n:,} rows ({bbls:,} distinct BBLs) — one per (BBL, year), final-period")
    print(f"  by year: {dict(by_year)}")
    return {"rows": n, "bbls": bbls}


# --------------------------------------------------------------------------- #
# Engine helper — READ-ONLY, tolerant of a missing table.
# --------------------------------------------------------------------------- #
def _table_exists(con: duckdb.DuckDBPyConnection) -> bool:
    return con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [TABLE]
    ).fetchone()[0] > 0


def taxable_series(con: duckdb.DuckDBPyConnection, bbl: str) -> list[dict]:
    """The subject's per-year transitional-taxable points, oldest→newest. Each carries its
    roll_year, value, period and exempt flag. Empty list if the table is absent. A year with
    no row simply does NOT appear here (the display renders it as a gap — never zero-filled)."""
    if not bbl or not _table_exists(con):
        return []
    rows = con.execute(
        f"""SELECT roll_year, curtxbtot, roll_period, is_exempt FROM {TABLE}
            WHERE parcel_id = ? ORDER BY roll_year""", [str(bbl).strip()]).fetchall()
    out = []
    for y, txb, period, exempt in rows:
        try:
            yr = int(y)
        except (TypeError, ValueError):
            continue
        out.append({"year": yr, "value": txb, "period": period, "exempt": bool(exempt)})
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Load the 2023–2027 transitional-taxable series.")
    ap.add_argument("--skip-fetch", action="store_true", help="reuse existing raw/, rebuild table")
    args = ap.parse_args(argv)
    print(f"=== Taxable-series loader: {config.ROLL_DATASET}  WHERE {WHERE} ===")
    manifest = load_manifest() if args.skip_fetch else fetch_series()
    print("=== Building DuckDB table ===")
    load_to_duckdb(manifest)
    print("Done.")


if __name__ == "__main__":
    main()
