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

## Post-v1 expansion path (ordered roadmap — not yet built)

v1 ships **Office (`O*`) only** (see DECISIONS.md). Expansion is deliberately sequential — each step is validated before the next is activated. The comp engine is **universal**; each product type is a **config addition, not an engine change.**

**1. Other class-4 commercial types, one at a time.** Retail `K*`, industrial `F*`, warehouse `E*`, garage `G*`, loft `L*`, etc. Each is activated individually with its own parcel-count-driven bucketing and comp-quality validation — the same method used for office. Until activated, a type returns the "out of scope for v1" refusal. No type is switched on wholesale.

**2. Class 2 multifamily — its own plugin, its own assessment logic.** A separate jurisdiction-style plugin, not a config tweak to the class-4 engine. Requirements recorded now so they are not forgotten:

- **Different ratio / cap rules.** Class 2 has statutory assessment-increase caps (8%/yr, 30%/5yr for buildings ≤10 units) that class 4 lacks. The **YoY-spike signal must be reinterpreted**: capped parcels cannot spike the way class 4 can, so a flat YoY is expected, not informative, for capped buildings.
- **Scope = whole-building rentals and coops.** Exclude residential **condo unit lots** (the same per-unit exclusion already applied to commercial condos).
- **RENT STABILIZATION HANDLING — OPEN QUESTION, NOT YET DECIDED.** The following is an **initial proposal only**; the final approach will be investigated and decided when class 2 is actually built, not now. Stabilized units carry below-market legal rents, so income-based assessments differ between otherwise-identical buildings by stabilization mix. The proposed handling:
  - (a) **Display** each parcel's stabilized-unit share as a **cited, published attribute** alongside building class and SF — descriptive only, letting the underwriter infer.
  - (b) **Caveat or refuse** the income-sensitive signals ($/unit, $/SF) when the stabilization mix is unknown or materially differs across the comp set — the same per-signal refusal discipline as missing SF.
  - (c) **Never compute a stabilization-adjusted value internally** — that would be a tool-invented estimate that crosses the honesty line.
  - Stabilized-unit counts would come from DOF rent-stabilization / tax-bill registration data — a **separate cited join with its own vintage.** **Revisit this explicitly when class 2 is built.**

## Deferred UI paths (backlog — design notes recorded, NOT scaffolded)

Recorded so the design constraints survive; none of this is built yet.

- **Custom comp-pool path.** A future mode where the user supplies their own comp set
  instead of the tool screening one. **When built, custom-pool output must carry a
  visible "comps were user-provided, not screened by the tool" stamp** — a provenance
  label held to the same discipline as the user-supplied NOI / operating-expense stamps,
  so a user-assembled set can never be mistaken for a tool-screened one.
- **Radius toggle.** A future control to adjust the comp search radius. **When built, the
  radius toggle applies to BOTH the autogenerate path and the custom-comp-pool path** (one
  control governs both), not to autogenerate alone.
- **Welcome / landing page.** Deferred; no design constraint recorded yet.

## Variance explanation is descriptive, never causal

Allowed: "This comp is assessed 20% higher and differs on: built 2015 vs 1980, class O5 vs O3, 40k SF vs 32k SF." Banned: "This comp is higher because it is newer."
