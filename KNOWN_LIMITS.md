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

  - **[A3 TEST TRIGGER — SF-less comp / $/SF exclusion path] Re-run A3 the first time a non-office product type is activated.** Finding on office: office comps have ~100% SF fill and the comp selector requires `sf IS NOT NULL` (and `curmkttot > 0`), so a SF-less COMP cannot occur in an office screen — verified, **0 of 160,156 comp rows across 4,874 screens**. Consequence: the comp-level `n/a` PSF render and the "SF-less comp excluded-not-zeroed from the `$/SF` (EMV-per-SF) distribution" logic are **unit-tested but never exercised on live office data** (the `n/a` PSF render only fires today when the *subject* lacks SF, which refuses the whole `$/SF` signal — not a per-comp exclusion). **Trigger:** a non-office type (retail `K*`, industrial `F*`, …) with lower SF fill can put a SF-less comp into a live comp set. Before trusting any `$/SF` distribution on that product type, run A3 for real: (a) confirm a mixed-SF comp table renders `n/a` on the SF-less comp rows and numeric PSF on the others; (b) confirm the SF-less comp is **dropped from the `$/SF` distribution n-count (not zeroed)** while still **counted in the assessed-value and tax-bill distributions**. Until then, the comp-level exclusion path is test-covered only.

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

- **[OPEN DECISION] Same-borough-default comp pull with explicit cross-borough opt-in.**
  The more correct long-term refinement over today's **disclosure-only** cross-borough note:
  default the comp pull to the subject's borough and require an explicit user opt-in to
  reach across a borough line, rather than pulling cross-borough comps and merely
  disclosing it. **Caveat:** borough is a **crude submarket proxy** — it does not capture
  intra-borough submarket lines (e.g. Midtown vs Downtown within Manhattan), so this is a
  first-cut boundary, not a true submarket fix. Revisit alongside the custom-pool work; not
  built now.

- **[OPEN DECISION] SF-band-width toggle and/or exact-vs-adjacent class-strictness toggle.**
  Whether to build either is **undecided** — revisit after the custom-pool work. Unlike the
  radius toggle (which is self-contained and was built now), both of these **reshape the
  comp set the way a custom pool does**: widening the SF band or loosening class strictness
  changes which parcels qualify, not just how far out the search reaches. If built, each
  would need a **"comp-selection parameters were user-adjusted" stamp** (same provenance
  discipline as user-supplied NOI / operating expense) and **its own validation pass**.
  Not scaffolded. Open question: do they get built at all, and if so do they share one
  "parameters adjusted" stamp or carry separate ones.

## Variance explanation is descriptive, never causal

Allowed: "This comp is assessed 20% higher and differs on: built 2015 vs 1980, class O5 vs O3, 40k SF vs 32k SF." Banned: "This comp is higher because it is newer."

## Abatement disclosure is ICAP-only; PILOT is undetectable

The Tax Bill region marks parcels (subject banner + comp tag) carrying a **current ICAP**
abatement, sourced from DOF Property Abatement Detail (`rgyu-ii48`, current snapshot =
max `extractdt`; `parid`/`tccode` are space-padded and trimmed). **Scope is ICAP only** for
v1 — it is ~89% of the office abatement signal and the clean building-level case. The flag
is **disclosure only**: the tool always plots the full statutory tax bill
(`curtxbtot × rate`) for the subject and every comp, abated or not, and the flag never
filters, sorts, or drops a comp.

- **Why CERP/CRP is dropped from v1 (it is NOT tax-neutral).** CERP/CRP is a **real
  property tax abatement that reduces a building's tax** — it is not excluded because it
  "doesn't affect taxes." It is dropped because it is **lease-level**: the benefit is tied
  to specific commercial *tenant leases*, not to the building, so it does not map cleanly to
  a building-level abatement flag (one BBL can carry many per-lease CERP rows). It is also a
  **small share of the office abatement signal — ~35 office BBLs vs ICAP's ~441 (roughly
  7%)**. SOLAR/J51/CONDO/COOP are dropped as residential or lease-level programs that
  likewise do not fit the building-level office flag.

- **[KNOWN GAP] PILOT is not detectable from available data.** Major office properties on
  public land (Hudson Yards, World Trade Center, Battery Park City) pay a negotiated PILOT
  instead of standard tax. PILOT does not appear in `rgyu-ii48`, and the `subject_tax_exempt`
  refusal does NOT catch them — e.g. `1000840036` (7 WTC, O4) carries a $555M positive
  market value and screens normally. A standing, **always-on** PILOT caveat under the Tax
  Bill chart discloses this; the tool makes no attempt to detect PILOT parcels. Revisit only
  if a PILOT/exempt-property source is identified.

## Commercial condos — not screenable on public data (three paths measured, all closed)

**Dated 2026-06-30.** Three distinct paths to screening commercial condos were measured
against source data; all three are closed. Recorded as measured, not assumed, so the boundary
is not re-litigated. **Source caveat:** every figure below was measured directly against NYC
Open Data (SODA API — assessment roll `8y4t-faws` FY2027 `period='3'` final; PLUTO `64uk-42ks`;
storefront datasets `92iy-9c3n` and `dxru-eun8`), independent of the tool's local DuckDB.

**PATH 1 — Building level: dead on value.** DOF books condo value on the individual unit
lots; the condo billing/base lot (lot ≥ 7501) is a square-footage shell with no value. Citywide
there are ~**11,495** billing lots: ~**99.8%** carry SF but only ~**3.2%** carry a positive
market value, and **0 of 10,957** R0 condo billing lots carry value at all. Building-level
parcels carrying value **and** SF **and** a retail-share split = **330** — but ~**325 are
residential** (R4 condo + D-code elevator apartments); genuinely commercial, predominantly-retail
(retail ≥ 0.80) = **2 citywide**: `4018609102` (Staten Island shopping center, K6) and
`1000168002` (RK retail condo). A building-level module would screen two buildings. Dead.

**PATH 2 — Unit level, value-aggregation: rejected to preserve comparison integrity.**
Building value *could* be reconstructed by summing the class-4 unit lots (~**99.9%** value fill
at the unit level). Rejected: a summed set of separately-assessed unit values is not the same
kind of number as DOF's single whole-building market value carried on a K-class comp, so it
cannot be placed on the same distribution honestly. Worse, pairing a partial-commercial *summed*
value against whole-building PLUTO SF produces a meaningless per-SF. Aggregation crosses the
comparison-integrity line and was not pursued.

**PATH 3 — Unit level, direct: comparability dead on data.** ~**7,395** predominantly-retail
(retail ≥ 0.80) commercial-condo unit lots carry their own value **and** SF, so the per-SF
arithmetic itself is clean. But retail-unit value is driven by **floor** (ground vs upper),
**corner-vs-inline**, **linear frontage feet**, and **grade level** — none of which the roll or
PLUTO expose at the unit level, so the tool would call two very different units "peers."
The NYC Storefront Registry was investigated as a rescue and does not supply them:
- Row-level asset `92iy-9c3n` ("Storefronts Reported Vacant or Not"): **414,884** rows, current
  through **2025** (reporting resumed — the "stalls at 2019" secondary reporting is wrong), BBL
  **100%** filled. It is a **vacancy + business-activity registry, not a physical-attributes
  registry**: it carries **no square footage, no floor, no rent** as published columns
  (confirmed against the dataset's own schema, not inferred from sample rows).
- Aggregate asset `dxru-eun8` ("Storefront Registration Class 2 and 4 Statistics") is
  census-tract / council-district level — useless for unit comping.
- No public NYC dataset exposes intra-building retail-unit comparability attributes. PLUTO
  `LotFrontage` and Digital Tax Map geometry approximate corner/frontage at the **building level
  only** and cannot distinguish two units inside the same building — exactly the discrimination
  this path required.

**CONCLUSION.** Commercial condos are not screenable on public data at either the building level
(no value on the billing lot) or the unit level (value present but comparability attributes
absent). Not a module; this entry is the record.

**One legitimate future use of the storefront data that is NOT comping.** `92iy-9c3n` does
cleanly carry per-BBL **vacancy status** and **business activity**. That could power a
**vacancy-status disclosure flag** on retail screens — a disclosure feature, not a comp signal,
and explicitly **not built in v1**. Recorded so the distinction (disclosure ≠ comparability) is
not lost.

## Custom comps: parcels without PLUTO coordinates cannot be user comps (measured 2026-07-07)

The per-comp validator requires PLUTO coordinates (distance is measured from the subject), so a
class-4 parcel with no PLUTO lat/lon is excluded with "no coordinates on record" at entry.
Measured against the loaded FY2027 class-4 roll + PLUTO 26v1, among otherwise-eligible comps
(non-condo-rule, positive market value):

- **O/K/F (the screenable types): 8 of 29,055 parcels (~0.03%)** — office 6/7,158 (0.08%,
  Manhattan office 3/2,477), retail 1/18,652, industrial 1/3,245. A footnote, not a coverage gap.
- **Other classes: 11,688 of 54,122 (~21.6%)** — dominated by **U-class utility parcels (10,172;
  rail corridors, transmission)** plus Z-misc (1,361), which PLUTO does not carry as mapped
  building lots. These are rarely sensible comps for anything.

**No UI disclosure needed**: the per-comp validation surfaces the exclusion on the specific comp
the moment it is entered — the disclosure is inherent to the flow. Recorded here so the ~20%
"other" number is never misread as an O/K/F coverage problem.

Related, fixed the same day: non-R-class parcels with lot >= 1001 (air-rights and other
conventionally high-numbered lots, e.g. 200 Park Ave = 1012809010 at lot 9010 — 62 O/K/F parcels
citywide) are excluded from comps by the same lot-range rule the auto engine uses, but are NOT
condo units — their exclusion reason names the lot-range rule, never asserts "condominium."
