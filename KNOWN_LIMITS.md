# KNOWN_LIMITS.md

What the tool refuses to do, and why. Refusal and provenance are features, not afterthoughts.

**No verdicts. No appeal advice.** Nearest commercial comp tool is **TaxNetUSA QuickAppeal** — Texas-only, paid, consultant-facing, and verdict-oriented. This tool differs: free, NYC-first, underwriter-facing, and it never renders a verdict. (See `PHASE0_DIFFERENTIATION.md`.)

## Hard refusals (built into code)

- **Below minimum comp count** → no distribution shown. Visible message, e.g. "only 5 comparable parcels found, below the 8-parcel minimum, no distribution shown." The tool never widens the comp net to hit the minimum.
- **Mixed tax classes or value fields** → throw error, never silently average across classes or across `cur`/`fin`/`ten` snapshots.
- **Blank/null fields** → excluded and counted, never zeroed.
- **No figure without its citation tuple** → if it can't carry source/version/roll year/retrieval date/parcel id, it does not display.

## Walled off entirely (roadmap or dead, never v1)

- Any tool-asserted market cap rate or comp-implied cap rate. Dead.
- Any true-value or over-assessment verdict ("you are over-assessed," "you should appeal," "true value is X"). Dead.
- Appeal-strategy learning from past outcomes. Roadmap, gated on a real appeal-outcome dataset that does not currently exist for the builder.
- Opex-margin checks. Roadmap with a flagged data dependency (opex benchmark data is largely gated/unpublished).
- Any ML or feedback loop that makes outputs non-deterministic. Dead for v1.

## Structural data limits (disclosed, not hidden)

- **RPIE / NOI is not published per parcel.** RUNG 3 is user-input NOI only. The constraint keeps it honest.
- **`curacttot` is mechanically 0.45 × `curmkttot`.** So an assessment-ratio-vs-45% check is informationless for class 4 — removed and replaced (see DECISIONS.md).
- **`8y4t-faws` is multi-year.** Every query must filter `year`, or counts and distributions silently blend roll years.
- **Condo billing-lot aggregation.** PLUTO aggregates condos to a billing lot; unmatched/aggregated parcels go to an exclusions table with a reason code.
- **Transitional assessment phase-in.** Class 4 has `curtrntot` (transitional) distinct from `curacttot` (actual). Lock which value field is compared; never mix.
- **YearBuilt reliability.** `yrbuilt` fill is 68% on class 4 → demoted to display-only.
- **Open-data vintage lag.** The API copy may lag the official DOF lookup; disclose any lag found in the ground-truth check.

## Variance explanation is descriptive, never causal

Allowed: "This comp is assessed 20% higher and differs on: built 2015 vs 1980, class O5 vs O3, 40k SF vs 32k SF." Banned: "This comp is higher because it is newer."
