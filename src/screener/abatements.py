"""ICAP abatement layer — DOF Property Abatement Detail (rgyu-ii48), current snapshot.

DISCLOSURE / PROVENANCE ONLY. This module marks which BBLs carry a CURRENT ICAP
abatement. It NEVER changes a computed tax figure — the tool always plots the full
statutory tax bill (curtxbtot x rate) for the subject and every comp, abated or not.
ICAP is the clean building-level program (~89% of office abatement signal); all other
programs (CERP/SOLAR/J51/CONDO/COOP/...) are lease-level or residential and out of scope
for v1.

Discipline mirrors loader.py: pull -> raw/ untouched -> typed DuckDB table with the same
provenance tuple as every sourced figure. Source quirks handled here:
  * parid is SPACE-PADDED to 30 chars -> trim() to a 10-digit BBL before joining.
  * tccode is space-padded too -> trim() then match exactly 'ICAP'.
  * Filter to the CURRENT snapshot = max(extractdt); a BBL may have many current ICAP
    rows (per benefit), so reduce to DISTINCT BBL = has-current-ICAP.

Run:
    python -m screener.abatements              # fetch + load
    python -m screener.abatements --skip-fetch # rebuild table from existing raw/
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

RAW_ABATE_DIR = config.RAW_DIR / "abatements"
TABLE = "abatements_icap"
PROGRAM = "ICAP"


def _token_headers() -> dict[str, str]:
    tok = os.environ.get("NYC_APP_TOKEN", "")
    return {"X-App-Token": tok} if tok else {}


# --------------------------------------------------------------------------- #
# Fetch — writes raw/ untouched
# --------------------------------------------------------------------------- #
def fetch_icap() -> dict:
    """Pull the current-snapshot ICAP rows verbatim to raw/abatements/. Returns manifest."""
    RAW_ABATE_DIR.mkdir(parents=True, exist_ok=True)
    url = config.SODA_BASE.format(dataset=config.ABATEMENT_DATASET)
    retrieval = date.today()
    with httpx.Client(headers=_token_headers()) as client:
        mx = client.get(url, params={"$select": "max(extractdt) as mx"}, timeout=120).json()[0]["mx"]
        where = f"extractdt='{mx}' AND tccode like '{PROGRAM}%'"
        rows: list[dict] = []
        offset = 0
        while True:
            page = client.get(url, params={
                "$select": "parid,tccode,extractdt", "$where": where,
                "$order": "parid", "$limit": 50000, "$offset": offset,
            }, timeout=300).json()
            if not page:
                break
            rows += page
            offset += 50000
            if len(page) < 50000:
                break
    path = RAW_ABATE_DIR / "icap_current.jsonl"
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    manifest = {
        "source_dataset": config.ABATEMENT_DATASET,
        "program": PROGRAM,
        "extractdt": mx[:10],
        "retrieval_date": retrieval.isoformat(),
        "where": where,
        "endpoint": url,
        "row_count": len(rows),
    }
    (RAW_ABATE_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"  pulled {len(rows):,} current {PROGRAM} rows (extractdt {mx[:10]}) -> {path}")
    return manifest


def load_manifest() -> dict:
    p = RAW_ABATE_DIR / "manifest.json"
    if not p.exists():
        sys.exit(f"No abatement manifest at {p}. Run a fetch first (omit --skip-fetch).")
    return json.loads(p.read_text())


# --------------------------------------------------------------------------- #
# Transform — typed DuckDB table, one row per BBL, provenance-stamped
# --------------------------------------------------------------------------- #
def load_to_duckdb(manifest: dict, db_path: Path | None = None) -> dict:
    db_path = db_path or config.DB_PATH
    glob = str(RAW_ABATE_DIR / "icap_current.jsonl")
    con = duckdb.connect(str(db_path))
    try:
        con.execute(f"DROP TABLE IF EXISTS {TABLE}")
        con.execute(f"""
            CREATE TABLE {TABLE} (
                parcel_id      VARCHAR NOT NULL,   -- trimmed 10-digit BBL
                program        VARCHAR NOT NULL,   -- 'ICAP'
                source_dataset VARCHAR NOT NULL,   -- 'rgyu-ii48'
                extractdt      DATE    NOT NULL,   -- current-snapshot vintage
                retrieval_date DATE    NOT NULL
            )""")
        con.execute(f"""
            INSERT INTO {TABLE}
            SELECT DISTINCT trim(parid) AS parcel_id, ? AS program, ? AS source_dataset,
                   ?::DATE AS extractdt, ?::DATE AS retrieval_date
            FROM read_json_auto('{glob}')
            WHERE trim(tccode) = ? AND trim(parid) <> ''
        """, [PROGRAM, manifest["source_dataset"], manifest["extractdt"],
              manifest["retrieval_date"], PROGRAM])
        n = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    finally:
        con.close()
    print(f"  {TABLE}: {n:,} distinct BBLs with current {PROGRAM} (extractdt {manifest['extractdt']})")
    return {"rows": n}


# --------------------------------------------------------------------------- #
# Engine helpers — READ-ONLY, tolerate a missing table (engine never hard-fails
# if the abatement load has not been run)
# --------------------------------------------------------------------------- #
def _table_exists(con: duckdb.DuckDBPyConnection) -> bool:
    return con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [TABLE]
    ).fetchone()[0] > 0


def icap_bbls(con: duckdb.DuckDBPyConnection, bbls: list[str]) -> set[str]:
    """Subset of `bbls` carrying a current ICAP abatement. Empty set if table absent."""
    keys = [str(b).strip() for b in bbls if b]
    if not keys or not _table_exists(con):
        return set()
    ph = ",".join(["?"] * len(keys))
    rows = con.execute(f"SELECT parcel_id FROM {TABLE} WHERE parcel_id IN ({ph})", keys).fetchall()
    return {r[0] for r in rows}


def icap_vintage(con: duckdb.DuckDBPyConnection) -> tuple[str | None, str | None]:
    """(extractdt ISO, source_dataset) for the current ICAP snapshot, or (None, None)."""
    if not _table_exists(con):
        return None, None
    row = con.execute(f"SELECT max(extractdt), any_value(source_dataset) FROM {TABLE}").fetchone()
    if not row or row[0] is None:
        return None, None
    return row[0].isoformat(), row[1]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Load current ICAP abatements into DuckDB.")
    ap.add_argument("--skip-fetch", action="store_true", help="reuse existing raw/, just rebuild")
    args = ap.parse_args(argv)
    print(f"=== ICAP abatement loader: {config.ABATEMENT_DATASET} (tccode={PROGRAM}, current snapshot) ===")
    manifest = load_manifest() if args.skip_fetch else fetch_icap()
    load_to_duckdb(manifest)
    print("Done.")


if __name__ == "__main__":
    main()
