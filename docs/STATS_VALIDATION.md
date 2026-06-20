# Stats-layer validation (run 2026-06-20)

`PYTHONPATH=src python scripts/validate_stats.py`. Per-signal distributions + subject
percentile for three subjects, plus a hand-check of the math.

## Subjects

### 1. Dense Manhattan office — `1000090001` (O4, ZIP 10004), 28 comps @ 0.5 mi, fully exact
| Signal | n | excl. blank | median | subject | percentile |
|---|---|---|---|---|---|
| assessed market value | 28 | 0 | 114,184,000 | 185,249,000 | 82.1 |
| tax bill (×0.10848) | 28 | 0 | 5,398,025 | 9,043,115 | 82.1 |
| $/gross-SF | 28 | 0 | 200.19 | 267.53 | 85.7 |
| phase-in gap | 26 | **2** | 0.0363 | −0.0152 | 3.85 |

### 2. Fallback-heavy — `2023070046` (O1 Bronx), 8 comps @ 1.0 mi, **1 exact + 7 O2 adjacent**
Caution fired: "comp set is largely adjacent-class …". assessed median 991,000, subject
1,323,000 → 62.5th pct; $/gross-SF median 142.09, subject 164.86 → 62.5th. All n=8, 0 blank.

### 3. Missing gross SF — `3053480042` (O9 Brooklyn), 11 comps @ 0.5 mi, `sf_band_applied=False`
assessed (n=11) and tax-bill (n=11) **compute**; **$/gross-SF REFUSES** with
`subject_no_gross_building_area` ("Market-value-per-SF unavailable, gross building area
missing for this parcel. Assessed-value and tax-bill distributions are unaffected.").
Confirms the locked per-signal refusal.

## Hand-verification (subject 2023070046, assessed market value)
Sorted comp values: 651k, 696k, 759k, 764k, 1,218k, 1,498k, 1,883k, 3,535k (n=8).
- median = mean(764k, 1,218k) = **991,000** — matches stats.
- subject 1,323,000; strictly below = 5 → percentile = 100·5/8 = **62.5** — matches.
- mean 1,375,500 and population stddev 915,248 — both match exactly.

## Correctness rules confirmed
1. Blanks excluded **and counted** per signal (phase-in gap dropped 2 of 28 for the dense subject).
2. Subject never in its own distribution/percentile (percentile is placement only).
3. Every signal carries `n`. Citation tuple + PLUTO version + exact/adjacent composition carried through.

## FINDING — tax-exempt ($0) comps distort the distributions (decision needed)
The dense O4 set includes **2 comps with `curmkttot = 0`** (e.g. `1000380001`, `1000420031` —
large offices, `curacttot=0`, `curtxbtot=0`): genuinely **tax-exempt** parcels, not nulls.
**29 office parcels citywide are exempt $0; none are null.** Per the locked rule only *nulls*
are blanks, so these real zeros are currently included — pulling `min` to 0 and dragging the
mean/median/percentile. (The phase-in-gap signal already drops them via its divide-by-`curacttot`
guard, so treatment is inconsistent across signals.)

**No behavior changed** — flagged for a decision. Options: (a) exclude non-positive market
value from the comp universe (exempt parcels aren't assessment peers — same spirit as the condo
exclusion); (b) exclude in stats with an `exempt_zero` reason code, counted separately from
blanks; (c) keep as-is. Recommend (a).

---

# Re-validation after the exempt exclusion (2026-06-20) — option (a) implemented

`curmkttot <= 0` parcels are now excluded from the comp universe (config
`exclude_non_positive_market_value`), routed to the `exclusions` table with reason
`NON_POSITIVE_MARKET_VALUE` (**1,629 class-4 parcels citywide**; 29 office), and a
tax-exempt **subject** gets a no-comparison refusal. 55 tests pass.

## Confirmations
- **Dense Manhattan `1000090001`**: comp set 28 → **26** (the 2 exempt $0 comps gone).
  Assessed-value **min 0 → 56,283,000**; median 114,184,000 → **119,726,500**; mean
  119.7M → **128.9M**; subject percentile 82.1 → **80.8**. $/gross-SF min 0 → **129.62**.
  (Phase-in gap unchanged at n=26 — it already dropped the zeros via its divide guard.)
- **Tax-exempt subject `1000380001`** (O4, curmkttot 0): **WHOLE-SCREEN REFUSAL**
  `subject_tax_exempt` → "this parcel has no positive market value (tax-exempt);
  assessment comparison does not apply."
- **Exclusions table** carries `NON_POSITIVE_MARKET_VALUE` with its count; provenance
  (`source_dataset`, version, roll_year, retrieval_date) travels on each excluded row.
- Fallback-heavy and no-SF subjects unchanged (their comps were all positive-value).

## Hand-verification re-run (subject `1000090001`, post-exclusion)
26 sorted comp values, 56,283,000 … 283,515,000.
- median = mean(index 12, 13) = **119,726,500** — matches stats.
- subject 185,249,000; 21 of 26 strictly below → percentile **80.77** — matches.
- mean 128,910,230.77 and population stddev 59,447,593.51 — both match exactly.

Math still exact after the exclusion.
