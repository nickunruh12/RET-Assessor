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

    # v1 scope + product bucketing
    activated_products: list[str] = ["O"]
    office_buckets: dict[str, str] = {}
    office_bucket_labels: dict[str, str] = {}
    fallback_ladder: dict[str, list[str]] = {}

    # gross-SF band
    sf_band: float = Field(gt=0, le=5)
    sf_required: bool = True

    # location = distance from PLUTO lat/lon, with radius-first expansion
    location_mode: str = "distance"
    radius_start_miles: float = Field(default=0.5, gt=0)
    radius_cap_miles: float = Field(default=1.0, gt=0)
    radius_step_miles: float = Field(default=0.1, gt=0)
    zip_prefilter: bool = False

    # condo exclusion + refusal threshold
    exclude_condo_unit_lots: bool = True
    condo_unit_lot_min: int = 1001
    exclude_non_positive_market_value: bool = True
    min_comp_count: int = 8

    # output guards + context rate
    low_exact_caution_threshold: int = 3
    class4_tax_rate: float = 0.10848

    # expense-ratio benchmark note (dynamic, config-driven)
    metro_name: str = ""
    product_type_labels: dict[str, str] = {}
    expense_ratio_benchmarks: dict[str, dict[str, list[float]]] = {}

    @classmethod
    def load(cls, path: Path | None = None) -> "CompCriteria":
        path = path or config.COMP_CRITERIA_PATH
        raw = json.loads(Path(path).read_text())
        return cls.model_validate(raw)


@runtime_checkable
class Jurisdiction(Protocol):
    """What a jurisdiction plugin must provide to the comp engine.

    The engine owns the generic mechanics (gross-SF band, great-circle distance,
    radius-first expansion, provenance). The plugin owns jurisdiction-specific
    knowledge: which products are activated, how the activated product's classes
    bucket, borough naming, and what counts as a condo unit lot.
    """

    name: str

    def borough_of(self, parcel_id: str) -> str:
        """Human borough name for a parcel id (display / subject summary)."""
        ...

    def is_activated_product(self, bldg_class: str | None, criteria: CompCriteria) -> bool:
        """True if this building class is an activated v1 product (office only at launch)."""
        ...

    def product_bucket(self, bldg_class: str | None, criteria: CompCriteria) -> str | None:
        """The comp bucket key for a building class (e.g. O5 -> 'O5_O6')."""
        ...

    def bucket_classes(self, bucket: str, criteria: CompCriteria) -> list[str]:
        """All building-class codes that map to a bucket (for the candidate filter)."""
        ...

    def exact_classes(self, bldg_class: str | None, criteria: CompCriteria) -> list[str]:
        """Tier-1 class set: the subject's own class for a low-rise code, or the whole
        grouped bucket for O5/O6 and O7/O8/O9 (which match within-bucket, no ladder)."""
        ...

    def adjacent_ladder(self, bldg_class: str | None, criteria: CompCriteria) -> list[str]:
        """Ordered adjacent classes added on fallback; [] for O4 and grouped buckets."""
        ...

    def product_bucket_label(self, bucket: str | None, criteria: CompCriteria) -> str:
        """Human label for a bucket key (display only)."""
        ...

    def condo_clause(self, criteria: CompCriteria) -> tuple[str, list]:
        """(sql_fragment, params) EXCLUDING condo unit lots; ('TRUE', []) if disabled."""
        ...

    def product_type(self, bldg_class: str | None, criteria: CompCriteria) -> str | None:
        """Product-type word for a building class (e.g. O* -> 'office'); None if unmapped."""
        ...


def get_jurisdiction(name: str) -> Jurisdiction:
    """Factory: resolve a jurisdiction plugin by name. New metro = new branch here."""
    if name == "nyc":
        from .plugins.nyc import NYC

        return NYC()
    raise ValueError(f"No jurisdiction plugin for '{name}'")
