"""Single-roll-year loader for the DOF assessment roll (8y4t-faws).

Contract (DECISIONS.md + INPUT_SPEC.md):
  * Pull 8y4t-faws filtered to curtaxclass='4' AND year='2027'.
  * The raw API response lands in raw/ UNTOUCHED — verbatim records, one JSON
    object per line, plus a manifest recording the provenance of the pull.
  * Transforms read the raw files and write NEW DuckDB tables. They never mutate
    the raw pull.
  * Every row of the derived table carries the full provenance tuple
    (source_dataset, dataset_version, roll_year, retrieval_date, parcel_id) as
    NOT NULL columns. A row without it cannot be inserted.

No LLM anywhere. Pure fetch + deterministic SQL.

Run:
    python -m screener.loader          # fetch + load
    python -m screener.loader --skip-fetch   # reload existing raw/ into DuckDB
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import httpx

from . import config
from .schema import Citation

RAW_ROLL_DIR = config.RAW_DIR / "roll"
PAGE_SIZE = 50_000  # SODA hard max per page
WHERE = f"{config.COL_TAX_CLASS}='{config.TAX_CLASS}' AND year='{config.ROLL_YEAR}'"


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #
def _app_token_headers() -> dict[str, str]:
    import os

    tok = os.environ.get("NYC_APP_TOKEN", "")
    return {"X-App-Token": tok} if tok else {}


def dataset_version(client: httpx.Client, dataset: str) -> str:
    """A real version anchor for the dataset: Socrata's rowsUpdatedAt epoch.

    This is the closest thing the roll has to a release string, and it changes
    whenever DOF republishes. Falls back to the retrieval date if metadata is
    unreachable, so the pull is never left without *some* version stamp.
    """
    url = f"https://data.cityofnewyork.us/api/views/{dataset}.json"
    try:
        r = client.get(url, headers=_app_token_headers(), timeout=60)
        r.raise_for_status()
        meta = r.json()
        epoch = meta.get("rowsUpdatedAt")
        if epoch:
            stamp = datetime.fromtimestamp(int(epoch), tz=timezone.utc).date().isoformat()
            return f"{dataset}@rowsUpdatedAt={epoch}({stamp})"
    except Exception as e:  # noqa: BLE001 — version stamp must never block a pull
        print(f"  [warn] could not read dataset metadata ({e}); using retrieval-date stamp")
    return f"{dataset}@retrieved={date.today().isoformat()}"


# --------------------------------------------------------------------------- #
# Fetch — writes raw/ untouched
# --------------------------------------------------------------------------- #
def fetch_roll(force: bool = True) -> dict:
    """Page the SODA endpoint and write verbatim records to raw/roll/.

    Returns the manifest dict (also written to raw/roll/manifest.json).
    """
    RAW_ROLL_DIR.mkdir(parents=True, exist_ok=True)
    url = config.SODA_BASE.format(dataset=config.ROLL_DATASET)
    retrieval = date.today()

    with httpx.Client(headers=_app_token_headers()) as client:
        version = dataset_version(client, config.ROLL_DATASET)
        print(f"  dataset_version = {version}")

        offset = 0
        page = 0
        total = 0
        while True:
            params = {
                "$where": WHERE,
                "$select": "*",
                "$order": f"{config.COL_BBL}",  # stable pagination
                "$limit": PAGE_SIZE,
                "$offset": offset,
            }
            r = client.get(url, params=params, timeout=300)
            r.raise_for_status()
            records = r.json()
            if not records:
                break
            # Write verbatim, one object per line. No transform.
            page_path = RAW_ROLL_DIR / f"page_{page:05d}.jsonl"
            with page_path.open("w") as f:
                for rec in records:
                    f.write(json.dumps(rec, separators=(",", ":")) + "\n")
            total += len(records)
            print(f"  page {page}: {len(records):,} rows (running total {total:,})")
            page += 1
            offset += PAGE_SIZE
            if len(records) < PAGE_SIZE:
                break

    manifest = {
        "source_dataset": config.ROLL_DATASET,
        "dataset_version": version,
        "roll_year": config.ROLL_YEAR,
        "tax_class": config.TAX_CLASS,
        "retrieval_date": retrieval.isoformat(),
        "where": WHERE,
        "endpoint": url,
        "row_count": total,
        "page_count": page,
        "page_glob": "page_*.jsonl",
    }
    (RAW_ROLL_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"  wrote {total:,} raw rows across {page} page file(s) -> {RAW_ROLL_DIR}")
    return manifest


def load_manifest() -> dict:
    path = RAW_ROLL_DIR / "manifest.json"
    if not path.exists():
        sys.exit(f"No manifest at {path}. Run a fetch first (omit --skip-fetch).")
    return json.loads(path.read_text())


# --------------------------------------------------------------------------- #
# Transform — new DuckDB tables, raw untouched
# --------------------------------------------------------------------------- #
def load_to_duckdb(manifest: dict, db_path: Path | None = None) -> dict:
    """Build raw_roll (verbatim) and roll_class4 (typed + provenance) tables.

    Exercises the Citation contract on the pull's provenance before writing, so a
    malformed provenance tuple fails loudly instead of silently stamping rows.
    """
    db_path = db_path or config.DB_PATH

    # Validate pull-level provenance through the locked schema. parcel_id is
    # row-level, so we use a sentinel here only to prove the tuple is well-formed;
    # the per-row parcel_id is enforced NOT NULL in SQL below.
    Citation(
        source_dataset=manifest["source_dataset"],
        dataset_version=manifest["dataset_version"],
        roll_year=manifest["roll_year"],
        retrieval_date=date.fromisoformat(manifest["retrieval_date"]),
        parcel_id="__pull_level__",
    )

    glob = str(RAW_ROLL_DIR / manifest["page_glob"])
    con = duckdb.connect(str(db_path))
    try:
        # 1. raw_roll: every column as-is (all VARCHAR). This mirrors raw/ and is
        #    never edited downstream.
        con.execute("DROP TABLE IF EXISTS raw_roll")
        con.execute(
            f"""
            CREATE TABLE raw_roll AS
            SELECT * FROM read_json_auto('{glob}', union_by_name=true, maximum_object_size=20000000)
            """
        )
        raw_n = con.execute("SELECT count(*) FROM raw_roll").fetchone()[0]

        # 2. roll_class4: ONE canonical row per BBL, typed + provenance stamped.
        #
        #    Structural finding: filtering year='2027' returns up to two snapshots
        #    per parcel via the `period` column — period='1' (tentative roll) and
        #    period='3' (final roll). 6,608 parcels carry a different curmkttot
        #    across the two periods, so the snapshot choice is not cosmetic.
        #    DECISIONS.md locks the FINAL roll as authoritative, so the canonical
        #    row per BBL is the highest period, tie-broken by latest extract date
        #    then a stable column for full determinism.
        #
        #    Provenance columns are NOT NULL; parcel_id (parid) NOT NULL. A row
        #    that cannot carry the full tuple cannot exist in this table.
        con.execute("DROP TABLE IF EXISTS roll_class4")
        con.execute(
            f"""
            CREATE TABLE roll_class4 (
                parcel_id        VARCHAR NOT NULL,
                source_dataset   VARCHAR NOT NULL,
                dataset_version  VARCHAR NOT NULL,
                roll_year        VARCHAR NOT NULL,
                retrieval_date   DATE    NOT NULL,
                roll_period      VARCHAR,           -- '3'=final, '1'=tentative (kept for transparency)
                tax_class        VARCHAR,
                bldg_class       VARCHAR,
                zip_code         VARCHAR,
                year_built       VARCHAR,           -- display-only (68% fill)
                gross_sqft       DOUBLE,            -- SF fallback when PLUTO misses
                curmkttot        DOUBLE,            -- market value: distribution basis
                curtxbtot        DOUBLE,            -- transitional taxable: tax-bill SIGNAL
                curtrntot        DOUBLE,            -- transitional assessed: phase-in gap
                curacttot        DOUBLE             -- actual assessed (0.45 x market)
            )
            """
        )
        con.execute(
            f"""
            INSERT INTO roll_class4
            SELECT
                {config.COL_BBL}                AS parcel_id,
                ?                               AS source_dataset,
                ?                               AS dataset_version,
                ?                               AS roll_year,
                ?::DATE                         AS retrieval_date,
                period                          AS roll_period,
                {config.COL_TAX_CLASS}          AS tax_class,
                {config.COL_BLDG_CLASS}         AS bldg_class,
                {config.COL_ZIP}                AS zip_code,
                {config.COL_YEAR_BUILT}         AS year_built,
                TRY_CAST({config.COL_GROSS_SQFT} AS DOUBLE)        AS gross_sqft,
                TRY_CAST({config.VALUE_FIELD_MARKET} AS DOUBLE)    AS curmkttot,
                TRY_CAST({config.VALUE_FIELD_TAXABLE} AS DOUBLE)   AS curtxbtot,
                TRY_CAST({config.VALUE_FIELD_TRANSITIONAL} AS DOUBLE) AS curtrntot,
                TRY_CAST({config.VALUE_FIELD_ACTUAL} AS DOUBLE)    AS curacttot
            FROM raw_roll
            WHERE {config.COL_BBL} IS NOT NULL AND {config.COL_BBL} != ''
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY {config.COL_BBL}
                ORDER BY period DESC, extracrdt DESC, easement NULLS FIRST, valref NULLS FIRST
            ) = 1
            """,
            [
                manifest["source_dataset"],
                manifest["dataset_version"],
                manifest["roll_year"],
                manifest["retrieval_date"],
            ],
        )
        derived_n = con.execute("SELECT count(*) FROM roll_class4").fetchone()[0]
        distinct_bbl = con.execute("SELECT count(DISTINCT parcel_id) FROM roll_class4").fetchone()[0]
        assert derived_n == distinct_bbl, f"dedup failed: {derived_n} rows vs {distinct_bbl} BBLs"
        dropped = raw_n - derived_n
    finally:
        con.close()

    print(f"  raw_roll:    {raw_n:,} rows (verbatim, both roll periods)")
    print(f"  roll_class4: {derived_n:,} canonical rows (one per BBL, final-period preferred);")
    print(f"               collapsed {dropped:,} duplicate-period rows")
    return {"raw_roll": raw_n, "roll_class4": derived_n, "collapsed_duplicate_period": dropped}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Load one DOF roll year into DuckDB.")
    ap.add_argument("--skip-fetch", action="store_true", help="reuse existing raw/, just (re)build tables")
    args = ap.parse_args(argv)

    print(f"=== Roll loader: {config.ROLL_DATASET}  WHERE {WHERE} ===")
    manifest = load_manifest() if args.skip_fetch else fetch_roll()
    print("=== Building DuckDB tables ===")
    counts = load_to_duckdb(manifest)
    print("Done.", counts)


if __name__ == "__main__":
    main()
