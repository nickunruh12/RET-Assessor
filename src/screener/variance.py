"""Variance explanation — descriptive attribute-diff over a comp set.

DESCRIPTIVE ONLY. Every output is a pure side-by-side difference between a comp and
the subject on published attributes. The layer NEVER states or implies WHY an
assessment differs — that would be a verdict. There is no LLM here and no causal
language anywhere: words like "because", "due to", "driven by", "explained by" are
forbidden. We state the differences; the human infers cause.

Surfacing is THREE transparent single-dimension views, never a blended similarity score:
  1. Nearest by DISTANCE      — closest comps by miles.
  2. Nearest by SF            — closest comps by gross-building-area difference.
  3. Most DIFFERENT by value  — largest curmkttot % difference (both directions).
Every "most similar"/"most different" claim traces to ONE visible dimension the user
can check. The full attribute-diff set stays queryable underneath the views.

Rationale (NOT user output): the nearest-by-distance and nearest-by-SF views are the
strong signal — if the subject is out of range of the comps most like it, that is the
legitimate red flag an underwriter cannot dismiss. The most-different view is context
for the distribution spread. The tool shows the picture and renders no verdict about it.

Year built is DISPLAY ONLY (68% fill) and is NEVER used to rank or sort.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .comps import CompRow, CompSet
from .schema import CitedRow


def _year_missing(y: str | None) -> bool:
    return y is None or str(y).strip() in ("", "0")


def _pct_diff(comp_val: float | None, subj_val: float | None) -> float | None:
    if comp_val is None or not subj_val:
        return None
    return round((comp_val - subj_val) / subj_val * 100.0, 2)


class VarianceRow(CitedRow):
    """One comp's attribute-diff vs the subject. Carries the citation tuple (via
    CitedRow) + the PLUTO version for the SF attribute, like every derived row.

    `differs_on` is the human-readable, verdict-free side-by-side string.
    """

    bldg_class: str | None
    subject_bldg_class: str | None
    match_type: str
    distance_miles: float
    curmkttot: float | None
    curtxbtot: float | None
    assessed_pct_diff: float | None      # (comp - subject) / subject EMV, %
    emv_psf_pct_diff: float | None       # (comp - subject) EMV-per-gross-SF, %  (sort key)
    sf: float | None
    subject_sf: float | None
    sf_pct_diff: float | None
    year_built: str | None               # display only
    year_built_missing: bool
    subject_year_built: str | None
    house_number: str | None             # display address (roll primary)
    street_name: str | None
    pluto_address: str | None            # display address (PLUTO fallback)
    stories: float | None                # display only; never used to rank or sort
    sf_dataset_version: str | None
    differs_on: str


@dataclass
class VarianceView:
    name: str
    dimension: str           # the SINGLE dimension this view is ordered by
    rows: list[VarianceRow]


@dataclass
class VarianceResult:
    subject_bbl: str
    subject: dict | None
    refused: bool
    note: str | None
    comp_count: int
    provenance: dict
    all_diffs: list[VarianceRow] = field(default_factory=list)   # full set, queryable
    views: dict[str, VarianceView] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
def _differs_on(comp: CompRow, subj: dict, assessed_pct: float | None,
                sf_pct: float | None) -> str:
    """Verdict-free side-by-side difference string. No causal language, ever."""
    # assessed value relation — magnitude + direction only, no cause.
    if assessed_pct is None:
        head = "Comp assessed value unavailable for comparison"
    elif assessed_pct > 0:
        head = f"Comp assessed {abs(assessed_pct):.0f}% higher than subject"
    elif assessed_pct < 0:
        head = f"Comp assessed {abs(assessed_pct):.0f}% lower than subject"
    else:
        head = "Comp assessed equal to subject"

    parts = [head, f"match {comp.match_type}"]
    parts.append(f"class {comp.bldg_class} vs {subj.get('bldg_class')}")

    if comp.sf is not None and subj.get("sf"):
        parts.append(f"SF {comp.sf:,.0f} vs {subj['sf']:,.0f} ({sf_pct:+.0f}%)")
    elif comp.sf is not None:
        parts.append(f"SF {comp.sf:,.0f} vs subject n/a")

    parts.append(f"distance {comp.distance_miles:.2f} mi")

    if _year_missing(comp.year_built):
        parts.append("year built n/a")
    else:
        subj_yr = subj.get("year_built")
        subj_yr_txt = subj_yr if not _year_missing(subj_yr) else "n/a"
        parts.append(f"year built {comp.year_built} vs {subj_yr_txt}")

    return "; ".join(parts)


def _psf(value: float | None, sf: float | None) -> float | None:
    return (value / sf) if (value is not None and sf) else None


def _to_variance_row(comp: CompRow, subj: dict) -> VarianceRow:
    assessed_pct = _pct_diff(comp.curmkttot, subj.get("curmkttot"))
    sf_pct = _pct_diff(comp.sf, subj.get("sf"))
    # EMV-per-gross-SF % diff — the sort key for the "most different" view so it matches
    # the displayed EMV-PSF column.
    emv_psf_pct = _pct_diff(_psf(comp.curmkttot, comp.sf), _psf(subj.get("curmkttot"), subj.get("sf")))
    return VarianceRow(
        citation=comp.citation,
        bldg_class=comp.bldg_class,
        subject_bldg_class=subj.get("bldg_class"),
        match_type=comp.match_type,
        distance_miles=comp.distance_miles,
        curmkttot=comp.curmkttot,
        curtxbtot=comp.curtxbtot,
        assessed_pct_diff=assessed_pct,
        emv_psf_pct_diff=emv_psf_pct,
        sf=comp.sf,
        subject_sf=subj.get("sf"),
        sf_pct_diff=sf_pct,
        year_built=comp.year_built,
        year_built_missing=_year_missing(comp.year_built),
        subject_year_built=subj.get("year_built"),
        house_number=comp.house_number,
        street_name=comp.street_name,
        pluto_address=comp.pluto_address,
        stories=comp.stories,
        sf_dataset_version=comp.sf_dataset_version,
        differs_on=_differs_on(comp, subj, assessed_pct, sf_pct),
    )


def compute_variance(cs: CompSet, view_size: int = 5) -> VarianceResult:
    """Attribute-diff every comp vs the subject; surface three single-dimension views."""
    subj = cs.subject

    if cs.refused or not cs.comps:
        return VarianceResult(
            subject_bbl=cs.subject_bbl, subject=subj, refused=True, note=cs.note,
            comp_count=cs.count, provenance={},
        )

    diffs = [_to_variance_row(c, subj) for c in cs.comps]

    c0 = cs.comps[0].citation
    provenance = {
        "source_dataset": c0.source_dataset,
        "dataset_version": c0.dataset_version,
        "roll_year": c0.roll_year,
        "retrieval_date": c0.retrieval_date.isoformat(),
        "sf_pluto_versions": sorted({d.sf_dataset_version for d in diffs if d.sf_dataset_version}),
        "year_built_note": "year built is display-only (68% fill); never used to rank or sort",
    }

    views: dict[str, VarianceView] = {}

    # 1. Nearest by DISTANCE — single dimension: distance_miles (asc).
    views["nearest_by_distance"] = VarianceView(
        "Nearest by Distance", "distance_miles",
        sorted(diffs, key=lambda d: d.distance_miles)[:view_size],
    )

    # 2. Nearest by SF — single dimension: |sf_pct_diff| (asc). Unavailable if the
    #    subject has no gross building area to difference against.
    if subj.get("sf"):
        sf_ranked = sorted(
            (d for d in diffs if d.sf_pct_diff is not None),
            key=lambda d: abs(d.sf_pct_diff),
        )
        views["nearest_by_sf"] = VarianceView(
            "Nearest by Gross Building Area", "abs(sf_pct_diff)", sf_ranked[:view_size]
        )
    else:
        views["nearest_by_sf"] = VarianceView(
            "Nearest by Gross Building Area (unavailable — subject has no gross building area)",
            "abs(sf_pct_diff)", [],
        )

    # 3. Most DIFFERENT by Estimated Market Value — ranked by the EMV-PER-GROSS-SF % diff
    #    so the sort key matches the displayed EMV-PSF column. Comps without gross SF have
    #    no PSF and are not rankable here. Both directions retained (sign visible per row).
    val_ranked = sorted(
        (d for d in diffs if d.emv_psf_pct_diff is not None),
        key=lambda d: abs(d.emv_psf_pct_diff), reverse=True,
    )
    views["most_different_by_assessed"] = VarianceView(
        "Most Different by Estimated Market Value", "abs(EMV-per-gross-SF % diff)", val_ranked[:view_size]
    )

    return VarianceResult(
        subject_bbl=cs.subject_bbl, subject=subj, refused=False, note=None,
        comp_count=cs.count, provenance=provenance, all_diffs=diffs, views=views,
    )
