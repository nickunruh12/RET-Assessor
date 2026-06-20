"""Generic jurisdiction interface for comp selection.

The comp engine (`comps.py`) is jurisdiction-agnostic: it knows about gross-SF
bands, excluding the subject, and carrying provenance, but it does NOT know how to
derive a borough from a parcel id, what counts as a condo, or how building classes
group. Those are jurisdiction-specific and live in a plugin module that implements
the `Jurisdiction` protocol below (per the architecture decision: a second metro is
a new plugin file, not a rewrite).

A jurisdiction supplies SQL *expressions* and *predicates* (not Python row logic),
so the engine can push the whole comp filter into one DuckDB query.

This module also defines `CompCriteria`, the validated view of
`config/comp_criteria.json` — the tunable parameters, kept out of code.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from . import config


class CompCriteria(BaseModel):
    """Validated, tunable comp-selection parameters (from config/comp_criteria.json)."""

    model_config = ConfigDict(extra="ignore")  # tolerate the _doc helper keys in the JSON

    jurisdiction: str
    sf_band: float = Field(gt=0, le=5)
    sf_required: bool = True
    class_match_level: str = "letter"          # "letter" | "exact"
    location_match: str = "borough_and_zip"     # "borough_and_zip" | "borough_only" | "zip_only"
    exclude_condo_unit_lots: bool = True
    condo_unit_lot_min: int = 1001
    min_comp_count: int = 8
    class_group_labels: dict[str, str] = {}

    @classmethod
    def load(cls, path: Path | None = None) -> "CompCriteria":
        path = path or config.COMP_CRITERIA_PATH
        raw = json.loads(Path(path).read_text())
        return cls.model_validate(raw)


@runtime_checkable
class Jurisdiction(Protocol):
    """What a jurisdiction plugin must provide to the comp engine.

    All methods return SQL fragments / expressions operating on a comp table that
    has at least `parcel_id`, `bldg_class`, and `zip_code` columns.
    """

    name: str

    def borough_of(self, parcel_id: str) -> str:
        """Human borough name for a parcel id (used for display / the subject summary)."""
        ...

    def class_group(self, bldg_class: str | None, criteria: CompCriteria) -> str | None:
        """The match key for a building class under the configured match level."""
        ...

    def class_group_label(self, group: str | None, criteria: CompCriteria) -> str:
        """Human label for a group key (display only)."""
        ...

    def class_group_sql(self, class_col: str, criteria: CompCriteria) -> str:
        """SQL expression computing the group key from a building-class column."""
        ...

    def location_clause(self, subject: dict, criteria: CompCriteria) -> tuple[str, list]:
        """(sql_fragment, params) restricting comps to the subject's location."""
        ...

    def condo_clause(self, criteria: CompCriteria) -> tuple[str, list]:
        """(sql_fragment, params) EXCLUDING condo unit lots; ('TRUE', []) if disabled."""
        ...


def get_jurisdiction(name: str) -> Jurisdiction:
    """Factory: resolve a jurisdiction plugin by name. New metro = new branch here."""
    if name == "nyc":
        from .plugins.nyc import NYC

        return NYC()
    raise ValueError(f"No jurisdiction plugin for '{name}'")
