"""Exemption layer — the roll's own curtxbextot (exempt portion of taxable), FY current.

DISCLOSURE / PROVENANCE ONLY. The roll carries the exempt slice of every parcel's taxable
value as a separate companion field (`curtxbextot`); what is actually billed on is
curtxbtot − curtxbextot. The tool ALWAYS plots the full statutory amount (curtxbtot x
rate) for the subject and every comp — this module never changes a computed figure. It
only records, per class-4 BBL, what share of the taxable value an exemption covers, so
exempt comps can be marked and an exempt subject gets the benefit-basis note.

This is a LOADER-FILTER WIDENING of the same roll dataset (8y4t-faws), not a new source:
same year, same final-period dedup (loader.FINAL_PERIOD_ORDER — no second period filter
is written), projected to the three columns the share needs. Discipline mirrors
loader.py/abatements.py: pull -> raw/ untouched -> typed DuckDB table with the standard
provenance tuple. Engine helpers are READ-ONLY and tolerate a missing table (an
already-deployed DB without this table simply shows no exemption marks).

Run:
    python -m screener.exemptions              # fetch + load
    python -m screener.exemptions --skip-fetch # rebuild table from existing raw/
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

RAW_EXEMPT_DIR = config.RAW_DIR / "exemptions"
TABLE = "exemptions_class4"
# Verbatim column projection — the share's inputs plus the dedup tiebreaker columns.
COLS = "parid,year,period,curtxbtot,curtxbextot,extracrdt,easement,valref"
WHERE = f"{config.COL_TAX_CLASS}='{config.TAX_CLASS}' AND year='{config.ROLL_YEAR}'"


def _token_headers() -> dict[str, str]:
    tok = os.environ.get("NYC_APP_TOKEN", "")
    return {"X-App-Token": tok} if tok else {}


# --------------------------------------------------------------------------- #
def fetch_exemptions() -> dict:
    """Page the current class-4 roll year (projected columns) verbatim to raw/.

    Pulls ALL class-4 rows, not just exempt ones: the final-period dedup must see every
    period for a parid, or a stale period's exemption could survive the reduction."""
    RAW_EXEMPT_DIR.mkdir(parents=True, exist_ok=True)
    url = config.SODA_BASE.format(dataset=config.ROLL_DATASET)
    retrieval = date.today()
    with httpx.Client(headers=_token_headers()) as client:
        version = dataset_version(client, config.ROLL_DATASET)
        print(f"  dataset_version = {version}")
        offset = page = total = 0
        while True:
            params = {"$where": WHERE, "$select": COLS,
                      "$order": config.COL_BBL, "$limit": PAGE_SIZE, "$offset": offset}
            recs = client.get(url, params=params, timeout=300).json()
            if not recs:
                break
            with (RAW_EXEMPT_DIR / f"page_{page:05d}.jsonl").open("w") as f:
                for r in recs:
                    f.write(json.dumps(r, separators=(",", ":")) + "\n")
            total += len(recs)
            page += 1
            offset += PAGE_SIZE
            if len(recs) < PAGE_SIZE:
                break
    manifest = {
        "source_dataset": config.ROLL_DATASET, "dataset_version": version,
        "roll_year": config.ROLL_YEAR, "tax_class": config.TAX_CLASS,
        "retrieval_date": retrieval.isoformat(), "where": WHERE, "endpoint": url,
        "row_count": total, "page_count": page, "page_glob": "page_*.jsonl",
        "columns": COLS,
    }
    (RAW_EXEMPT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"  wrote {total:,} raw rows across {page} page file(s) -> {RAW_EXEMPT_DIR}")
    return manifest


def load_manifest() -> dict:
    p = RAW_EXEMPT_DIR / "manifest.json"
    if not p.exists():
        sys.exit(f"No exemption manifest at {p}. Run a fetch first (omit --skip-fetch).")
    return json.loads(p.read_text())


# --------------------------------------------------------------------------- #
def load_to_duckdb(manifest: dict, db_path: Path | None = None) -> dict:
    """Build exemptions_class4: one row per exempt BBL (curtxbextot > 0 after the SHARED
    final-period dedup). exempt_share = curtxbextot / curtxbtot, the citable fraction of
    taxable value the exemption covers."""
    db_path = db_path or config.DB_PATH
    glob = str(RAW_EXEMPT_DIR / manifest["page_glob"])
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
                curtxbtot      DOUBLE,             -- taxable value (pre-exemption)
                curtxbextot    DOUBLE,             -- exempt portion of taxable
                exempt_share   DOUBLE              -- curtxbextot / curtxbtot, clamped to [0, 1]
            )""")
        con.execute(f"""
            INSERT INTO {TABLE}
            WITH final_rows AS (
                SELECT {config.COL_BBL} AS parcel_id,
                       TRY_CAST(curtxbtot AS DOUBLE) AS txb,
                       TRY_CAST(curtxbextot AS DOUBLE) AS txbex
                FROM read_json_auto('{glob}', union_by_name=true)
                WHERE {config.COL_BBL} IS NOT NULL AND {config.COL_BBL} != ''
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY {config.COL_BBL}
                    ORDER BY {FINAL_PERIOD_ORDER}
                ) = 1
            )
            SELECT parcel_id, ? AS source_dataset, ? AS dataset_version,
                   ? AS roll_year, ?::DATE AS retrieval_date,
                   txb, txbex, LEAST(GREATEST(txbex / txb, 0), 1) AS exempt_share
            FROM final_rows
            WHERE txbex > 0 AND txb > 0
        """, [manifest["source_dataset"], manifest["dataset_version"],
              manifest["roll_year"], manifest["retrieval_date"]])
        n = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
        full = con.execute(f"SELECT count(*) FROM {TABLE} WHERE exempt_share >= 0.995").fetchone()[0]
    finally:
        con.close()
    print(f"  {TABLE}: {n:,} exempt class-4 BBLs (FY{manifest['roll_year']}; {full:,} fully exempt)")
    return {"rows": n}


# --------------------------------------------------------------------------- #
# Engine helpers — READ-ONLY, tolerant of a missing table.
# --------------------------------------------------------------------------- #
def _table_exists(con: duckdb.DuckDBPyConnection) -> bool:
    return con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [TABLE]
    ).fetchone()[0] > 0


def exempt_shares(con: duckdb.DuckDBPyConnection, bbls: list[str]) -> dict[str, float]:
    """bbl -> exempt share of taxable value (0-1], for the subset of `bbls` carrying an
    exemption on the current roll. Empty dict if the table is absent."""
    keys = [str(b).strip() for b in bbls if b]
    if not keys or not _table_exists(con):
        return {}
    ph = ",".join(["?"] * len(keys))
    rows = con.execute(
        f"SELECT parcel_id, exempt_share FROM {TABLE} WHERE parcel_id IN ({ph})", keys).fetchall()
    return {r[0]: r[1] for r in rows}


def exemptions_vintage(con: duckdb.DuckDBPyConnection) -> tuple[str | None, str | None]:
    """(roll_year, source_dataset) for the loaded exemption slice, or (None, None)."""
    if not _table_exists(con):
        return None, None
    row = con.execute(
        f"SELECT any_value(roll_year), any_value(source_dataset) FROM {TABLE}").fetchone()
    if not row or row[0] is None:
        return None, None
    return row[0], row[1]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Load class-4 exemption shares into DuckDB.")
    ap.add_argument("--skip-fetch", action="store_true", help="reuse existing raw/, rebuild table")
    args = ap.parse_args(argv)
    print(f"=== Exemption loader: {config.ROLL_DATASET}  WHERE {WHERE} ===")
    manifest = load_manifest() if args.skip_fetch else fetch_exemptions()
    print("=== Building DuckDB table ===")
    load_to_duckdb(manifest)
    print("Done.")


if __name__ == "__main__":
    main()
