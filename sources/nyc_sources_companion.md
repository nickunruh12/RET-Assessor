# NYC source document — human-readable companion

Companion to `nyc_sources.json`. This file is itself a portfolio artifact: it proves you understand the jurisdiction's mechanics cold. The JSON is what the data layer reads; this is what a reviewer reads.

## How NYC class 4 assessment actually works (the mechanics you must be able to defend)

NYC does not assess at market value. The Department of Finance estimates a **market value** for each parcel, then applies a class-specific **assessment ratio** to get the **assessed value** the tax is actually levied on. For tax class 4 (commercial/industrial) that ratio is **45%** of market value. The **tax bill** is then assessed value (after exemptions/abatements and after any transitional phase-in) times the **class 4 tax rate** — **10.848% for FY2026** (confirm exact figure against the DOF tax-rate table).

Two wrinkles that bite:

1. **Transitional assessment phase-in.** Large assessment changes on class 4 are phased in over several years, so a parcel can have an *actual* assessed value and a different *transitional* assessed value in the same year. The tool must lock exactly which value field it compares (Phase 2 Step 2) and never mix them across comps.
2. **No cap on class 4.** Unlike class 1/2 residential, class 4 has no annual assessment-increase cap, so a single-year jump to full market value is legal. That is why the **YoY assessment-spike** SIGNAL is meaningful here — a 40% jump is not automatically an error.

## Why the roll needs PLUTO

The assessment roll (`8y4t-faws`) has no reliable building-square-footage field. Comparability for commercial property leans heavily on **SF** and **building class**, both of which come from **PLUTO** (`64uk-42ks`, field `BldgArea` and `BldgClass`), joined on **BBL**. That join is the spine of the comp engine — and its match rate is itself a Phase 2 finding to record, not assume.

## Why RUNG 3 must be user-input NOI

The assessor's NOI comes from owner-filed **RPIE** statements, which are **not published per parcel**. You cannot auto-compute an implied cap rate. The user must bring their own NOI, and the output is stamped "based on the NOI you provided." That constraint is the feature: it keeps a user-derived number from ever masquerading as a public one.

## Citation discipline

Every field in the JSON has either a `citation_url` (locked) or a `verify_against_dof` / `PENDING` flag (not yet locked). Nothing displays in the tool from a field still marked PENDING. The Phase 2 run fills the dataset vintages and locks the value-field meaning; the remaining CONTEXT citations (reassessment cycle, RET/transfer tax, appeal deadline) are pulled directly from DOF / Tax Commission / NY State before the CONTEXT panel is built in Phase 6.

## Open items carried into Phase 2

- Exact value-field column name and meaning (final market value vs actual vs transitional assessed)
- Roll year + PLUTO version string at retrieval
- Exact FY2026 class 4 rate from the official DOF table
- Reassessment cycle, RET/transfer tax citations, appeal deadline (CONTEXT, can lag to Phase 6)
