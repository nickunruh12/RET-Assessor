# RUNG 3 validation (run 2026-06-21)

`PYTHONPATH=src python scripts/validate_rung3.py`. The one user-supplied number, fenced.

## Behaviors confirmed

**Off by default.** A standard call (no `enabled=True`) does not run: returns
`enabled=False, computed=False` with "RUNG 3 is off by default…". Never part of standard output.

**(a) Normal positive NOI** on a valid subject (`1000090001`, market value $185,249,000):
> Your NOI of $12,000,000 implies a 6.48% cap rate on the DOF market value of $185,249,000 (based on the NOI you provided).

One line. Possessive ("Your NOI … implies"), stamped ("based on the NOI you provided").
`user_noi` carries `source=user_supplied` and **no citation**; `market_value` is cited to
`8y4t-faws@2027`. Cap rate = NOI / market value = 12,000,000 / 185,249,000 = **6.48%**.

**(b) Junk NOI — rejected, nothing computed:**
| input | reason |
|---|---|
| `0`, negative | `noi_not_positive` |
| non-numeric, empty string, `None`, bool, NaN/inf | `noi_non_numeric` |

Message: "NOI must be a positive number. Zero, negative, or non-numeric input is rejected
— no cap rate is computed." No division performed.

**(c) Tax-exempt subject** (`1000380001`, curmkttot 0): refuses to run, returns the
existing no-comparison message ("this parcel has no positive market value (tax-exempt);
assessment comparison does not apply"). No division.

## Partition proof (structural separation from public outputs)
- RUNG 3 result is a distinct type (`Rung3Result`) carrying `partition="RUNG_3_USER_SUPPLIED"`.
- Field intersection with public outputs: `Rung3Result ∩ StatsResult = {subject_bbl}`
  (a key, not a value); `∩ SignalStats = {}`; `∩ VarianceRow = {}`.
- The `partition` marker exists on **no** public object (stats/signal/variance).
- Shared fields beyond `subject_bbl`: **none**. A user-derived number cannot blend into a
  public distribution.

## Formula note (flagged for confirmation)
The brief's prose wrote the formula as "market value ÷ NOI", but an implied **cap rate** is
**NOI ÷ market value** (value÷NOI yields a multiple, not the "X%" the brief asks for).
Implemented the standard, correct cap-rate definition so the percentage is meaningful;
the formula is one line in `rung3.py` if a true value÷NOI multiple is ever wanted instead.

## Rationale (locked)
RUNG 3 must be user-input because the assessor's actual NOI comes from RPIE, which NYC
does not publish per parcel — it cannot be auto-pulled. That dependency keeps it honest.
