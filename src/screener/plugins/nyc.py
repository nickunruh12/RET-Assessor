"""NYC jurisdiction plugin — implements the Jurisdiction interface for comp selection.

All NYC-specific knowledge lives here:
  * BBL structure: 10 digits = borough(1) + block(5) + lot(4). Borough digit 1-5.
  * v1 activated product = Office (building class O*). Other class-4 commercial
    classes are out of scope until individually activated.
  * Office bucketing (config-driven): O1-O4 exact, O5+O6 grouped, O7+O8+O9 grouped.
  * Condo unit lots: building class R*, or lot number >= condo_unit_lot_min (1001).

Distance ranking and radius logic are generic and handled by the comp engine using
PLUTO latitude/longitude; the plugin does not touch geometry.
"""
from __future__ import annotations

from ..jurisdiction import CompCriteria

_BOROUGH = {
    "1": "Manhattan",
    "2": "Bronx",
    "3": "Brooklyn",
    "4": "Queens",
    "5": "Staten Island",
}


class NYC:
    name = "nyc"

    # --- borough -----------------------------------------------------------
    def borough_of(self, parcel_id: str) -> str:
        return _BOROUGH.get((parcel_id or " ")[0], "Unknown")

    # --- v1 product scope --------------------------------------------------
    def is_activated_product(self, bldg_class: str | None, criteria: CompCriteria) -> bool:
        letter = (bldg_class or "").strip()[:1]
        return bool(letter) and letter in criteria.activated_products

    # --- office bucketing --------------------------------------------------
    def product_bucket(self, bldg_class: str | None, criteria: CompCriteria) -> str | None:
        if not bldg_class:
            return None
        code = bldg_class.strip()
        # Configured map first; fall back to the exact code as its own bucket so an
        # unmapped office code (e.g. a future O0) still matches only itself.
        return criteria.office_buckets.get(code, code)

    def bucket_classes(self, bucket: str, criteria: CompCriteria) -> list[str]:
        codes = [c for c, b in criteria.office_buckets.items() if b == bucket]
        return codes or [bucket]  # fallback: the bucket key is itself the class code

    def product_bucket_label(self, bucket: str | None, criteria: CompCriteria) -> str:
        if bucket is None:
            return "Unknown"
        return criteria.office_bucket_labels.get(bucket, bucket)

    # --- condo exclusion ---------------------------------------------------
    def condo_clause(self, criteria: CompCriteria) -> tuple[str, list]:
        if not criteria.exclude_condo_unit_lots:
            return "TRUE", []
        # Exclude class R* OR lot number (BBL digits 7-10) >= condo_unit_lot_min.
        return (
            "(bldg_class NOT LIKE 'R%' "
            "AND TRY_CAST(substr(parcel_id, 7, 4) AS INTEGER) < ?)",
            [criteria.condo_unit_lot_min],
        )
