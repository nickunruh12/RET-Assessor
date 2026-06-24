"""Expense Ratio Check — user-operating-expense vs the subject's derived real-estate tax.

A second user-supplied-number feature, fenced like RUNG 3. It computes ONE ratio:

    real-estate tax share = (subject real estate taxes) / (user operating expense)

where the subject's real estate taxes are the SAME derived figure used for the Tax Bill
chart: curtxbtot (transitional taxable) x the FY2026 class-4 rate. It is NOT recomputed
differently here — the caller passes that derived figure in.

Discipline (mirrors RUNG 3):
  * Possessive, stamped output; operating expense labelled user-supplied with NO citation;
    the tax figure cites the roll.
  * Guardrails: opex must be a positive finite number (zero/negative/non-numeric rejected,
    never computed); a tax-exempt subject (curmkttot <= 0) cannot run.
  * No LLM, pure arithmetic. No verdict, no "high/low".

The descriptive benchmark NOTE is built in serialize.py from config (per metro/product
type), not here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import duckdb

from . import config
from .comps import REFUSAL_MESSAGES
from .jurisdiction import CompCriteria

PARTITION = "EXPENSE_RATIO_USER_SUPPLIED"


@dataclass
class ExpenseRatioResult:
    partition: str
    subject_bbl: str
    computed: bool
    statement: str | None
    stamp: str | None
    ratio_pct: float | None
    real_estate_taxes: float | None
    user_opex: float | None
    opex_source: str
    rejected: bool
    rejection_reason: str | None   # subject_not_found / subject_tax_exempt /
                                   # opex_not_positive / opex_non_numeric
    message: str | None


def _result(subject_bbl, **kw) -> ExpenseRatioResult:
    base = dict(
        partition=PARTITION, subject_bbl=subject_bbl, computed=False, statement=None,
        stamp=None, ratio_pct=None, real_estate_taxes=None, user_opex=None,
        opex_source="user_supplied", rejected=False, rejection_reason=None, message=None,
    )
    base.update(kw)
    return ExpenseRatioResult(**base)


def _coerce_positive(x) -> tuple[float | None, str | None]:
    """(value, None) for a positive finite number, else (None, reason)."""
    if isinstance(x, bool):
        return None, "opex_non_numeric"
    if isinstance(x, (int, float)):
        val = float(x)
    elif isinstance(x, str):
        try:
            val = float(x.strip())
        except (ValueError, AttributeError):
            return None, "opex_non_numeric"
    else:
        return None, "opex_non_numeric"
    if not math.isfinite(val):
        return None, "opex_non_numeric"
    if val <= 0:
        return None, "opex_not_positive"
    return val, None


def compute_expense_ratio(real_estate_taxes, user_opex, roll_stamp: str, rate: float,
                          subject_bbl: str = "") -> ExpenseRatioResult:
    """Pure compute. `real_estate_taxes` is the already-derived curtxbtot x rate figure."""
    stamp = (f"operating expense: user-supplied (no citation) · real estate taxes derived "
             f"from {roll_stamp} (curtxbtot × {rate})")

    # Tax-exempt subject (no positive taxes) cannot run — no ratio.
    if real_estate_taxes is None or real_estate_taxes <= 0:
        return _result(subject_bbl, rejected=True, rejection_reason="subject_tax_exempt",
                       message=REFUSAL_MESSAGES["subject_tax_exempt"], stamp=stamp)

    opex, reason = _coerce_positive(user_opex)
    if opex is None:
        msg = ("Operating expense must be a positive number. Zero, negative, or non-numeric "
               "input is rejected — no ratio is computed.")
        return _result(subject_bbl, rejected=True, rejection_reason=reason, message=msg, stamp=stamp)

    ratio = real_estate_taxes / opex
    statement = (f"Your real estate taxes of ${real_estate_taxes:,.0f} are {ratio * 100:.0f}% "
                 f"of the operating expense you provided (${opex:,.0f}).")
    return _result(subject_bbl, computed=True, statement=statement, stamp=stamp,
                   ratio_pct=round(ratio * 100, 2), real_estate_taxes=real_estate_taxes,
                   user_opex=opex)


def run_expense_ratio(con: duckdb.DuckDBPyConnection, subject_bbl: str, user_opex,
                      criteria: CompCriteria, comp_table: str = "parcels") -> ExpenseRatioResult:
    """Fetch the subject, derive real estate taxes (curtxbtot x rate), compute the ratio."""
    rate = criteria.class4_tax_rate
    rows = con.execute(
        f"""SELECT parcel_id, source_dataset, roll_year, curmkttot, curtxbtot
            FROM {comp_table} WHERE parcel_id = ?""",
        [subject_bbl],
    ).fetchall()
    if not rows:
        return _result(subject_bbl, rejected=True, rejection_reason="subject_not_found",
                       message=REFUSAL_MESSAGES["subject_not_found"])

    _, source_dataset, roll_year, curmkttot, curtxbtot = rows[0]
    roll_stamp = f"{source_dataset}@{roll_year}"

    # Tax-exempt subject -> no ratio (parallels the comp/RUNG 3 refusal).
    if curmkttot is None or curmkttot <= 0:
        stamp = (f"operating expense: user-supplied (no citation) · real estate taxes derived "
                 f"from {roll_stamp} (curtxbtot × {rate})")
        return _result(subject_bbl, rejected=True, rejection_reason="subject_tax_exempt",
                       message=REFUSAL_MESSAGES["subject_tax_exempt"], stamp=stamp)

    re_taxes = curtxbtot * rate if curtxbtot is not None else None
    return compute_expense_ratio(re_taxes, user_opex, roll_stamp, rate, subject_bbl)
