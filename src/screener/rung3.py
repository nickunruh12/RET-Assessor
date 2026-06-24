"""RUNG 3 — user-NOI implied cap rate. The ONLY place a user-supplied number enters
the tool, so the entire module is about fencing that number off from public data.

Discipline (DECISIONS.md 2026-06-21):
  1. OFF BY DEFAULT — runs only when explicitly enabled; never part of standard output.
  2. STAMPED user-supplied — every output reads "based on the NOI you provided"; the
     framing is possessive ("your NOI implies X%"), never "the cap rate is X%".
  3. PARTITIONED — a structurally separate result object (this is NOT a SignalStats /
     VarianceRow), never blended into the public distributions, so a user-derived number
     can never be mistaken for a public one.
  4. NO LLM — pure arithmetic.

Guardrails: NOI must be a positive finite number (zero/negative/non-numeric rejected,
never computed); a tax-exempt subject (curmkttot <= 0) cannot run (no division).

WHY user-input: the assessor's actual NOI comes from RPIE, which NYC does NOT publish
per parcel, so it cannot be auto-pulled — that dependency is what keeps RUNG 3 honest.

NOTE ON THE FORMULA: an implied cap rate is NOI / market value (a %). The subject's
market value carries its roll citation; the NOI is stamped user_supplied with NO citation
(it is not public).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import duckdb

from . import config
from .comps import REFUSAL_MESSAGES
from .schema import Citation

# Structural partition marker — present on every RUNG 3 result, absent from every
# public signal/variance object. Used to prove (and enforce) the separation.
PARTITION = "RUNG_3_USER_SUPPLIED"
STAMP = "based on the NOI you provided"


@dataclass
class Rung3Result:
    partition: str          # always PARTITION — structural separation from public outputs
    subject_bbl: str
    enabled: bool
    computed: bool
    stamp: str              # the user-supplied stamp
    # the one number (None unless computed)
    implied_cap_rate: float | None      # decimal, e.g. 0.0685
    implied_cap_rate_pct: float | None  # 6.85
    statement: str | None               # possessive, stamped line
    # inputs kept distinct by source
    user_noi: float | None              # user_supplied — NO citation (not public)
    noi_source: str                     # always "user_supplied"
    market_value: float | None          # subject curmkttot (public)
    market_value_citation: dict | None  # the roll citation tuple for the market value
    # control / rejection
    rejected: bool
    rejection_reason: str | None        # disabled / subject_not_found / subject_tax_exempt /
                                        # noi_non_numeric / noi_not_positive
    message: str | None


def _result(subject_bbl, **kw) -> Rung3Result:
    base = dict(
        partition=PARTITION, subject_bbl=subject_bbl, enabled=True, computed=False,
        stamp=STAMP, implied_cap_rate=None, implied_cap_rate_pct=None, statement=None,
        user_noi=None, noi_source="user_supplied", market_value=None,
        market_value_citation=None, rejected=False, rejection_reason=None, message=None,
    )
    base.update(kw)
    return Rung3Result(**base)


def _coerce_positive_noi(noi) -> tuple[float | None, str | None]:
    """Return (value, None) for a positive finite number, else (None, reason)."""
    if isinstance(noi, bool):                       # bool is an int subclass — reject
        return None, "noi_non_numeric"
    if isinstance(noi, (int, float)):
        val = float(noi)
    elif isinstance(noi, str):
        try:
            val = float(noi.strip())
        except (ValueError, AttributeError):
            return None, "noi_non_numeric"
    else:
        return None, "noi_non_numeric"
    if not math.isfinite(val):
        return None, "noi_non_numeric"
    if val <= 0:
        return None, "noi_not_positive"
    return val, None


def compute_rung3(subject_market_value, market_value_citation: Citation | None,
                  user_noi, subject_bbl: str = "", *, enabled: bool = False) -> Rung3Result:
    """Core, pure RUNG 3 computation. No I/O. implied cap rate = NOI / market value."""
    # 1. OFF BY DEFAULT.
    if not enabled:
        return _result(subject_bbl, enabled=False, message=(
            "RUNG 3 is off by default. Enable it to compute an implied cap rate from "
            "the NOI you provide."))

    # 2. Subject must have a positive market value (tax-exempt cannot run — no division).
    if subject_market_value is None or subject_market_value <= 0:
        return _result(subject_bbl, rejected=True, rejection_reason="subject_tax_exempt",
                       message=REFUSAL_MESSAGES["subject_tax_exempt"])

    # 3. NOI guardrail — reject junk, never compute a cap rate from garbage.
    noi, reason = _coerce_positive_noi(user_noi)
    if noi is None:
        msg = ("NOI must be a positive number. Zero, negative, or non-numeric input is "
               "rejected — no cap rate is computed.")
        return _result(subject_bbl, rejected=True, rejection_reason=reason, message=msg)

    # 4. The one number. Possessive framing, stamped, market value cited, NOI uncited.
    cap = noi / subject_market_value
    cite = market_value_citation.model_dump(mode="json") if market_value_citation else None
    # Sentence drops the "(based on the NOI you provided)" parenthetical; the stamp is
    # still carried in `stamp` and rendered as the page's footer line below the sentence.
    statement = (f"Your NOI of ${noi:,.0f} implies a {cap * 100:.2f}% cap rate on the "
                 f"DOF market value of ${subject_market_value:,.0f}.")
    return _result(
        subject_bbl, computed=True, implied_cap_rate=round(cap, 6),
        implied_cap_rate_pct=round(cap * 100, 4), statement=statement,
        user_noi=noi, market_value=subject_market_value, market_value_citation=cite,
    )


def run_rung3(con: duckdb.DuckDBPyConnection, subject_bbl: str, user_noi, *,
              enabled: bool = False, comp_table: str = "parcels") -> Rung3Result:
    """Fetch the subject's market value + citation from the roll, then compute RUNG 3."""
    if not enabled:
        return compute_rung3(None, None, user_noi, subject_bbl, enabled=False)

    rows = con.execute(
        f"""SELECT parcel_id, source_dataset, dataset_version, roll_year, retrieval_date,
                   curmkttot
            FROM {comp_table} WHERE parcel_id = ?""",
        [subject_bbl],
    ).fetchall()
    if not rows:
        return _result(subject_bbl, rejected=True, rejection_reason="subject_not_found",
                       message=REFUSAL_MESSAGES["subject_not_found"])

    r = rows[0]
    citation = Citation(
        source_dataset=r[1], dataset_version=r[2], roll_year=r[3],
        retrieval_date=r[4], parcel_id=r[0],
    )
    return compute_rung3(r[5], citation, user_noi, subject_bbl, enabled=True)
