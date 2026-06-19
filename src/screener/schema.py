"""Citation schema — the provenance contract for every derived row.

Non-negotiable rule (DECISIONS.md: provenance over persuasion): every derived row
must carry the full provenance tuple

    (source_dataset, dataset_version, roll_year, retrieval_date, parcel_id)

A row that cannot carry this tuple must not be constructible. This is enforced
here, structurally, before any data is loaded:

  * `Citation` has all five fields required (no defaults) and is frozen. It rejects
    empty/blank strings, so you cannot slip a placeholder past it.
  * `CitedRow` requires a `Citation`. Every derived-row model subclasses it, so no
    derived row can exist without provenance attached.

Nothing in this module touches a network or a database. It is pure structure.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, field_validator


class Citation(BaseModel):
    """The provenance tuple stamped onto every derived row.

    Frozen and validated. Construction fails if any field is missing or blank,
    which is the mechanism that makes an un-cited derived row impossible to build.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_dataset: str   # Socrata dataset id, e.g. "8y4t-faws" or "64uk-42ks"
    dataset_version: str  # exact version/roll string recorded at retrieval, e.g. "PLUTO 26v1"
    roll_year: str        # assessment roll year, e.g. "2027"
    retrieval_date: date  # date the source row was pulled
    parcel_id: str        # BBL / parid this row describes

    @field_validator("source_dataset", "dataset_version", "roll_year", "parcel_id")
    @classmethod
    def _non_blank(cls, v: str, info) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError(f"{info.field_name} must be a non-empty string (provenance cannot be blank)")
        return v.strip()


class CitedRow(BaseModel):
    """Base for every derived-row model. Carries — and requires — a Citation.

    Subclass this for each transformed table row (parcel facts, comp rows,
    exclusions, SIGNAL outputs). Because `citation` has no default, a subclass
    instance cannot be constructed without provenance.
    """

    model_config = ConfigDict(extra="forbid")

    citation: Citation
