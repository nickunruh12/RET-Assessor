#!/usr/bin/env python3
"""Variance-layer validation — 3 subjects, three views each, + a banned-word scan.

Subjects: one assessment in line with its nearest comps, one out-of-range/outlier vs
its nearest comps, one with missing-vintage comps. Confirms: no causal language in any
output string (grep returns clean), vintage shown-when-present and never used to sort,
every row carries provenance, and the full attribute-diff set stays queryable.

    PYTHONPATH=src python scripts/validate_variance.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import duckdb  # noqa: E402

from screener import config  # noqa: E402
from screener.comps import select_comps  # noqa: E402
from screener.jurisdiction import CompCriteria, get_jurisdiction  # noqa: E402
from screener.variance import compute_variance  # noqa: E402

INLINE = "1000100016"          # assessed ~50th percentile of its comps
OUTLIER = "1000090014"         # assessed ~96th percentile of its comps
MISSING_VINTAGE = "3001720050"  # Brooklyn O2, comps with missing year built

# Causal phrasing that would turn a difference into a verdict — must never appear.
BANNED = ["because", "due to", "driven by", "explained by", "caused by",
          "results from", "result of", "leads to", "owing to", "thanks to",
          "as a result", "attributable to", "reason"]

_captured: list[str] = []   # every string emitted, for the banned-word scan


def emit(s: str = "") -> None:
    _captured.append(s)
    print(s)


def show(vr) -> None:
    s = vr.subject
    emit("\n" + "=" * 82)
    emit(f"SUBJECT {vr.subject_bbl}  {s['bldg_class']} ({s['bucket_label']})  "
         f"{s['borough']}  SF {s['sf']:,.0f}  year built {s.get('year_built')}  "
         f"curmkttot {s['curmkttot']:,.0f}")
    if vr.refused:
        emit(f"  REFUSED: {vr.note}")
        return
    emit(f"  comps: {vr.comp_count}   full attribute-diff set queryable underneath "
         f"(all_diffs n={len(vr.all_diffs)})")
    emit(f"  provenance: roll {vr.provenance['source_dataset']} v={vr.provenance['dataset_version']} "
         f"roll_year={vr.provenance['roll_year']} retrieved {vr.provenance['retrieval_date']}")
    emit(f"  SF source PLUTO {vr.provenance['sf_pluto_versions']}")
    emit(f"  note: {vr.provenance['year_built_note']}")
    for key in ("nearest_by_distance", "nearest_by_sf", "most_different_by_assessed"):
        v = vr.views[key]
        emit(f"\n  ▸ {v.name}   [ordered by: {v.dimension}]")
        for d in v.rows:
            emit(f"      {d.citation.parcel_id}  {d.differs_on}")
            emit(f"          provenance: {d.citation.source_dataset}@{d.citation.roll_year} "
                 f"retr {d.citation.retrieval_date}  SF-src {d.sf_dataset_version}")


def main():
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    crit = CompCriteria.load()
    juris = get_jurisdiction(crit.jurisdiction)
    for bbl in (INLINE, OUTLIER, MISSING_VINTAGE):
        show(compute_variance(select_comps(con, bbl, juris, crit)))

    # --- queryable check: dump a couple of raw attribute-diffs for one subject ---
    vr = compute_variance(select_comps(con, INLINE, juris, crit))
    emit("\n" + "=" * 82)
    emit(f"FULL-SET QUERYABLE CHECK — subject {INLINE}: {len(vr.all_diffs)} attribute-diff rows; "
         f"e.g. filter assessed_pct_diff > 25%:")
    for d in [x for x in vr.all_diffs if x.assessed_pct_diff and x.assessed_pct_diff > 25][:4]:
        emit(f"   {d.citation.parcel_id}  assessed {d.assessed_pct_diff:+.0f}%  "
             f"SF {d.sf_pct_diff:+.0f}%  dist {d.distance_miles:.2f}mi  match {d.match_type}")

    # --- banned-word scan over EVERY emitted string ---
    emit("\n" + "=" * 82)
    haystack = "\n".join(_captured).lower()
    hits = sorted({w for w in BANNED if w in haystack})
    emit(f"BANNED-CAUSAL-WORD SCAN over {len(_captured)} output lines: "
         f"{'CLEAN — no causal language' if not hits else 'FOUND: ' + str(hits)}")
    con.close()
    if hits:
        sys.exit(1)


if __name__ == "__main__":
    main()
