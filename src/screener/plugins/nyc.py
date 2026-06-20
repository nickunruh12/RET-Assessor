"""NYC jurisdiction plugin — implements the Jurisdiction interface for comp selection.

All NYC-specific knowledge lives here:
  * BBL structure: 10 digits = borough(1) + block(5) + lot(4). Borough digit 1-5.
  * Building-class grouping: by first letter (major use category) or exact code.
  * Condo unit lots: building class R*, or lot number >= condo_unit_lot_min (1001).
  * Location: borough is derived from the BBL; ZIP is the roll `zip_code`.

It returns SQL fragments so the comp engine can run one DuckDB query.
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

    # --- building-class grouping ------------------------------------------
    def class_group(self, bldg_class: str | None, criteria: CompCriteria) -> str | None:
        if not bldg_class:
            return None
        if criteria.class_match_level == "exact":
            return bldg_class.strip()
        return bldg_class.strip()[:1] or None  # "letter": major use category

    def class_group_label(self, group: str | None, criteria: CompCriteria) -> str:
        if group is None:
            return "Unknown"
        if criteria.class_match_level == "exact":
            return criteria.class_group_labels.get(group[:1], group)
        return criteria.class_group_labels.get(group, group)

    def class_group_sql(self, class_col: str, criteria: CompCriteria) -> str:
        if criteria.class_match_level == "exact":
            return f"trim({class_col})"
        return f"substr(trim({class_col}), 1, 1)"

    # --- location ----------------------------------------------------------
    def location_clause(self, subject: dict, criteria: CompCriteria) -> tuple[str, list]:
        boro_expr = "substr(parcel_id, 1, 1)"
        subj_boro = (subject["parcel_id"] or " ")[0]
        subj_zip = subject.get("zip_code")

        if criteria.location_match == "borough_only":
            return f"{boro_expr} = ?", [subj_boro]
        if criteria.location_match == "zip_only":
            return "zip_code = ?", [subj_zip]
        # default: borough_and_zip
        return f"({boro_expr} = ? AND zip_code = ?)", [subj_boro, subj_zip]

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
