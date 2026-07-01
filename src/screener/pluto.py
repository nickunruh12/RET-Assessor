"""PLUTO join — primary gross-building-area source for the class-4 parcels.

The SF metric is gross building area (PLUTO `BldgArea`), not usable/rentable area.

Contract (DECISIONS.md):
  * Physical characteristics come from PLUTO 64uk-42ks; `BldgArea` (gross building
    area) is the PRIMARY source (99.98% fill on commercial vs 71.8% for the roll's
    gross_sqft, itself a gross-building-area figure used as fallback).
  * Join roll_class4 -> PLUTO on BBL. Every class-4 parcel that fails to match
    PLUTO is routed to an exclusions table with a reason code. The PLUTO match
    rate is a reported finding.
  * Raw PLUTO lands in raw/ untouched. Transforms build new DuckDB tables only.
  * Each derived row carries its roll provenance tuple AND cites the PLUTO source
    + version for the gross-building-area value. No row exists without provenance.

BBL formats differ: the roll's `parid` is a 10-char string ("1002230035"); PLUTO's
`bbl` is a float string ("1002230035.00000000"). Both are normalized to BIGINT for
the join.

Run (after the roll loader):
    python -m screener.pluto                 # fetch PLUTO + join
    python -m screener.pluto --skip-fetch    # reuse raw/pluto/, rejoin
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
from .loader import _app_token_headers, dataset_version
from .schema import Citation

RAW_PLUTO_DIR = config.RAW_DIR / "pluto"
PAGE_SIZE = 50_000
# Only the columns the join needs. Keeps the raw pull lean (858k lots citywide).
# latitude/longitude feed distance-based comp ranking (DECISIONS 2026-06-19).
# numfloors (display-only stories, gated on fill) + address (display-address fallback).
PLUTO_COLS = "bbl,bldgarea,lotarea,bldgclass,landuse,yearbuilt,areasource,version,latitude,longitude,numfloors,address"


def fetch_pluto() -> dict:
    """Page PLUTO (selected columns) and write verbatim records to raw/pluto/."""
    RAW_PLUTO_DIR.mkdir(parents=True, exist_ok=True)
    url = config.SODA_BASE.format(dataset=config.PLUTO_DATASET)
    retrieval = date.today()

    with httpx.Client(headers=_app_token_headers()) as client:
        version_anchor = dataset_version(client, config.PLUTO_DATASET)
        print(f"  pluto dataset_version anchor = {version_anchor}")

        offset = page = total = 0
        versions: set[str] = set()
        while True:
            params = {
                "$select": PLUTO_COLS,
                "$order": "bbl",
                "$limit": PAGE_SIZE,
                "$offset": offset,
            }
            r = client.get(url, params=params, timeout=300)
            r.raise_for_status()
            records = r.json()
            if not records:
                break
            page_path = RAW_PLUTO_DIR / f"page_{page:05d}.jsonl"
            with page_path.open("w") as f:
                for rec in records:
                    v = rec.get("version")
                    if v:
                        versions.add(v)
                    f.write(json.dumps(rec, separators=(",", ":")) + "\n")
            total += len(records)
            print(f"  page {page}: {len(records):,} rows (running total {total:,})")
            page += 1
            offset += PAGE_SIZE
            if len(records) < PAGE_SIZE:
                break

    # PLUTO's own `version` column is the authoritative release string (e.g. "25v1").
    version = f"{config.PLUTO_DATASET} version={'|'.join(sorted(versions)) or 'unknown'} ({version_anchor})"
    manifest = {
        "source_dataset": config.PLUTO_DATASET,
        "dataset_version": version,
        "roll_year": config.ROLL_YEAR,  # the roll year this PLUTO pull supports
        "retrieval_date": retrieval.isoformat(),
        "select": PLUTO_COLS,
        "endpoint": url,
        "row_count": total,
        "page_count": page,
        "page_glob": "page_*.jsonl",
        "pluto_versions_seen": sorted(versions),
    }
    (RAW_PLUTO_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"  wrote {total:,} raw PLUTO rows across {page} page file(s) -> {RAW_PLUTO_DIR}")
    return manifest


def load_manifest() -> dict:
    path = RAW_PLUTO_DIR / "manifest.json"
    if not path.exists():
        sys.exit(f"No PLUTO manifest at {path}. Run a fetch first (omit --skip-fetch).")
    return json.loads(path.read_text())


def join(manifest: dict, db_path: Path | None = None) -> dict:
    """Build pluto_lots, parcels (matched + SF), and exclusions; return match stats."""
    db_path = db_path or config.DB_PATH

    # Validate PLUTO provenance through the locked schema before stamping rows.
    Citation(
        source_dataset=manifest["source_dataset"],
        dataset_version=manifest["dataset_version"],
        roll_year=manifest["roll_year"],
        retrieval_date=date.fromisoformat(manifest["retrieval_date"]),
        parcel_id="__pull_level__",
    )

    glob = str(RAW_PLUTO_DIR / manifest["page_glob"])
    con = duckdb.connect(str(db_path))
    try:
        if con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name='roll_class4'"
        ).fetchone()[0] != 1:
            sys.exit("roll_class4 not found. Run the roll loader first.")

        # 1. pluto_raw (verbatim) + pluto_lots (normalized BBL + typed BldgArea).
        con.execute("DROP TABLE IF EXISTS pluto_raw")
        con.execute(
            f"CREATE TABLE pluto_raw AS SELECT * FROM read_json_auto('{glob}', union_by_name=true)"
        )
        con.execute("DROP TABLE IF EXISTS pluto_lots")
        con.execute(
            """
            CREATE TABLE pluto_lots AS
            SELECT
                TRY_CAST(bbl AS BIGINT)        AS bbl_int,
                TRY_CAST(bldgarea AS DOUBLE)   AS bldgarea,
                TRY_CAST(lotarea AS DOUBLE)    AS lotarea,
                bldgclass                       AS pluto_bldgclass,
                version                         AS pluto_version,
                TRY_CAST(latitude AS DOUBLE)   AS latitude,
                TRY_CAST(longitude AS DOUBLE)  AS longitude,
                TRY_CAST(numfloors AS DOUBLE)  AS numfloors,
                address                         AS pluto_address
            FROM pluto_raw
            WHERE TRY_CAST(bbl AS BIGINT) IS NOT NULL
            QUALIFY ROW_NUMBER() OVER (PARTITION BY TRY_CAST(bbl AS BIGINT)
                                       ORDER BY TRY_CAST(bldgarea AS DOUBLE) DESC NULLS LAST) = 1
            """
        )

        # 2. parcels: roll_class4 LEFT JOIN pluto_lots on normalized BBL.
        #    Gross-building-area source = PLUTO BldgArea (primary); fall back to roll
        #    gross_sqft when PLUTO has no usable gross building area. Every row keeps the roll
        #    provenance tuple and additionally cites the PLUTO source + version for
        #    the gross-building-area value.
        con.execute("DROP TABLE IF EXISTS parcels")
        con.execute(
            """
            CREATE TABLE parcels AS
            SELECT
                r.*,
                p.bldgarea                                  AS pluto_bldgarea,
                p.lotarea                                   AS pluto_lotarea,
                p.pluto_bldgclass,
                p.pluto_version,
                p.latitude                                  AS pluto_latitude,
                p.longitude                                 AS pluto_longitude,
                p.numfloors                                 AS pluto_numfloors,
                p.pluto_address,
                CASE WHEN p.bbl_int IS NOT NULL THEN ? ELSE NULL END  AS pluto_source_dataset,
                CASE WHEN p.bbl_int IS NOT NULL THEN ? ELSE NULL END  AS pluto_dataset_version,
                CASE WHEN p.bbl_int IS NOT NULL THEN ?::DATE ELSE NULL END AS pluto_retrieval_date,
                CASE
                    WHEN p.bldgarea IS NOT NULL AND p.bldgarea > 0 THEN p.bldgarea
                    WHEN r.gross_sqft IS NOT NULL AND r.gross_sqft > 0 THEN r.gross_sqft
                    ELSE NULL
                END                                          AS sf,
                CASE
                    WHEN p.bldgarea IS NOT NULL AND p.bldgarea > 0 THEN 'pluto_bldgarea'
                    WHEN r.gross_sqft IS NOT NULL AND r.gross_sqft > 0 THEN 'roll_gross_sqft_fallback'
                    ELSE NULL
                END                                          AS sf_source
            FROM roll_class4 r
            LEFT JOIN pluto_lots p
              ON TRY_CAST(r.parcel_id AS BIGINT) = p.bbl_int
            """,
            [manifest["source_dataset"], manifest["dataset_version"], manifest["retrieval_date"]],
        )

        # 3. exclusions: comp-universe exclusion audit, one row per (parcel, reason).
        #    A parcel may appear under more than one reason (e.g. no SF AND exempt).
        #      NO_PLUTO_MATCH            — BBL not present in PLUTO (mostly condo unit lots)
        #      PLUTO_MATCH_NO_AREA       — matched but PLUTO BldgArea is null/<=0
        #      NON_POSITIVE_MARKET_VALUE — curmkttot <= 0 (tax-exempt; not an assessment peer)
        con.execute("DROP TABLE IF EXISTS exclusions")
        con.execute(
            """
            CREATE TABLE exclusions AS
            SELECT parcel_id, source_dataset, dataset_version, roll_year, retrieval_date,
                   bldg_class, zip_code,
                   CASE
                     WHEN pluto_bldgclass IS NULL THEN 'NO_PLUTO_MATCH'
                     ELSE 'PLUTO_MATCH_NO_AREA'
                   END AS reason_code,
                   CASE WHEN sf_source = 'roll_gross_sqft_fallback' THEN sf ELSE NULL END AS fallback_sf
            FROM parcels
            WHERE pluto_bldgarea IS NULL OR pluto_bldgarea <= 0
            UNION ALL
            SELECT parcel_id, source_dataset, dataset_version, roll_year, retrieval_date,
                   bldg_class, zip_code, 'NON_POSITIVE_MARKET_VALUE' AS reason_code,
                   NULL AS fallback_sf
            FROM parcels
            WHERE curmkttot <= 0 OR curmkttot IS NULL
            """
        )

        # 4. parcels_no_sf: persisted set of parcels with NO gross building area
        #    from any tier (PLUTO BldgArea or roll gross_sqft). These are ineligible
        #    for the $/SF SIGNAL but still appear in the assessed-value and tax-bill
        #    distributions. Persisted as a real table, not just a query.
        con.execute("DROP TABLE IF EXISTS parcels_no_sf")
        con.execute(
            """
            CREATE TABLE parcels_no_sf AS
            SELECT parcel_id, source_dataset, dataset_version, roll_year, retrieval_date,
                   bldg_class, zip_code, curmkttot, curtxbtot
            FROM parcels
            WHERE sf IS NULL
            """
        )

        total = con.execute("SELECT count(*) FROM parcels").fetchone()[0]
        matched = con.execute("SELECT count(*) FROM parcels WHERE pluto_bldgclass IS NOT NULL").fetchone()[0]
        no_match = con.execute("SELECT count(*) FROM exclusions WHERE reason_code='NO_PLUTO_MATCH'").fetchone()[0]
        no_area = con.execute("SELECT count(*) FROM exclusions WHERE reason_code='PLUTO_MATCH_NO_AREA'").fetchone()[0]
        non_positive = con.execute("SELECT count(*) FROM exclusions WHERE reason_code='NON_POSITIVE_MARKET_VALUE'").fetchone()[0]
        rescued = con.execute("SELECT count(*) FROM exclusions WHERE fallback_sf IS NOT NULL").fetchone()[0]
        no_sf_anywhere = con.execute("SELECT count(*) FROM parcels WHERE sf IS NULL").fetchone()[0]
        sf_from_pluto = con.execute("SELECT count(*) FROM parcels WHERE sf_source='pluto_bldgarea'").fetchone()[0]
        sf_from_fallback = con.execute("SELECT count(*) FROM parcels WHERE sf_source='roll_gross_sqft_fallback'").fetchone()[0]
        pluto_n = con.execute("SELECT count(*) FROM pluto_lots").fetchone()[0]
    finally:
        con.close()

    stats = {
        "class4_parcels": total,
        "pluto_lots_loaded": pluto_n,
        "matched_to_pluto": matched,
        "pluto_match_rate": round(matched / total, 4) if total else 0.0,
        "excluded_no_pluto_match": no_match,
        "excluded_pluto_match_no_area": no_area,
        "excluded_non_positive_market_value": non_positive,
        "excluded_total": no_match + no_area,
        "excluded_rescued_by_roll_fallback": rescued,
        "no_usable_sf_anywhere": no_sf_anywhere,
        "sf_from_pluto_bldgarea": sf_from_pluto,
        "sf_from_roll_fallback": sf_from_fallback,
    }
    print("\n=== PLUTO join result ===")
    print(f"  class-4 parcels (roll):      {total:,}")
    print(f"  PLUTO lots loaded:           {pluto_n:,}")
    print(f"  matched to PLUTO:            {matched:,}")
    print(f"  >>> PLUTO MATCH RATE:        {stats['pluto_match_rate']:.2%}")
    print(f"  excluded NO_PLUTO_MATCH:     {no_match:,}  (mostly condo unit lots)")
    print(f"  excluded PLUTO_MATCH_NO_AREA:{no_area:,}")
    print(f"  excluded NON_POSITIVE_MARKET_VALUE: {non_positive:,}  (tax-exempt; not assessment peers)")
    print(f"  ...of excluded, rescued by roll gross_sqft fallback: {rescued:,}")
    print(f"  no gross building area anywhere: {no_sf_anywhere:,}")
    print(f"  SF from PLUTO BldgArea:      {sf_from_pluto:,}  (primary)")
    print(f"  SF from roll gross_sqft:     {sf_from_fallback:,}  (fallback)")
    return stats


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Join class-4 roll to PLUTO for gross building area (BldgArea).")
    ap.add_argument("--skip-fetch", action="store_true", help="reuse raw/pluto/, just rejoin")
    args = ap.parse_args(argv)

    print(f"=== PLUTO join: {config.PLUTO_DATASET} ===")
    manifest = load_manifest() if args.skip_fetch else fetch_pluto()
    stats = join(manifest)
    print("\nDone.", json.dumps(stats))


if __name__ == "__main__":
    main()
