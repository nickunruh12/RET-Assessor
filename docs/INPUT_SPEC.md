# Phase 3 — Input design spec

**Persona.** The user is a CRE underwriter sanity-checking a tax basis during a deal, not a property owner. The inputs map to what an underwriter has at hand: a target address/BBL, sometimes a deal price (purchase-vs-assessed gap), sometimes an NOI assumption (RUNG 3).

**Principle.** The tool must produce the distribution from address or BBL alone. An underwriter screening a target may not have an NOI assumption yet; forcing inputs you don't need is friction. Every optional field is offered, none gates execution, each is labeled with what it improves. Missing input narrows output, never blocks it, never gets guessed.

## Tier 0 — required (the only thing required to run)

| Field | Purpose | Resolution |
|---|---|---|
| **Address or BBL** | Resolves the parcel, builds the comp distribution | Address → BBL via NYC Geoclient/Geosupport (free, needs key). BBL used directly if supplied. |

Tool runs and shows where comparable assessments sit **before asking for anything else**.

## Tier 1 — optional, sharpens the signal

| Field | What it improves |
|---|---|
| User's own assessed value | Shows their exact percentile in the distribution |
| Confirmation of building class | Corrects a stale/mis-coded PLUTO `BldgClass` |
| Confirmation of gross building area | Corrects stale PLUTO `BldgArea` (gross building area) |
| Vintage (year built) | Display-only context; failed the Phase 2 fill gate (68%) so it is not a comp criterion |

## Tier 2 — optional, CONTEXT enrichment or RUNG 3

| Field | Powers | Output discipline |
|---|---|---|
| **Purchase price + date** | Purchase-vs-DOF-market-value SIGNAL | Cited gap, no verdict: "deal price X on [date] vs DOF market value Y, a Z% gap." Both numbers real → rung-1 arithmetic. |
| **NOI** | RUNG 3 implied cap rate | Off by default. Output stamped "based on the NOI you provided." No comparison rate, no verdict, visually partitioned from public figures. |

## Behavior rules

- Tier 0 alone → full distribution + the four public SIGNAL comparisons (assessed-value distribution/percentile, tax-bill distribution/percentile, market-value-per-gross-building-area percentile, and the phase-in gap (transitional vs actual assessed)). The $/SF SIGNAL is a peer-comparison screen against comps, not a reconstruction of DOF's class-4 valuation method (which is income-based); its denominator is gross building area (PLUTO `BldgArea`, roll `gross_sqft` fallback).
- Supplying Tier 2 purchase price → adds the purchase-vs-market gap SIGNAL.
- Loading two roll years (engine parameter, not a user field) → adds the YoY assessment-change-vs-comp-set SIGNAL.
- Enabling RUNG 3 toggle + entering NOI → adds the implied-cap-rate line, partitioned.
- Below the minimum comp count → visible refusal, regardless of how many optional fields were supplied.

## $/SF output contract (RECORDED — not yet implemented)

Every market-value-per-gross-building-area figure must display the source of its
gross-building-area **denominator**, tied to the row's `sf_source` tag, **every time**.
No unlabeled $/SF output is permitted. The label rides on the $/SF figure itself in
the user output — the same provenance discipline as the citation tuple.

| `sf_source` | Label shown with the $/SF figure |
|---|---|
| `pluto_bldgarea` | "based on gross building area (PLUTO [version])" |
| `roll_gross_sqft` | "based on gross building area (DOF assessment roll)" |
| `derived_dimensions` | "based on ESTIMATED gross building area (frontage × depth × stories, not a reported figure)" |
| no SF from any tier | per-signal refusal: "Market-value-per-SF unavailable, gross building area missing for this parcel" — shown alongside the assessed-value and tax-bill distributions, which do not need gross building area |

Notes:
- The refusal is **per-signal**, not a whole-tool refusal: a parcel with no gross
  building area still gets the assessed-value and tax-bill distributions.
- `derived_dimensions` is a separate, opt-in tier (frontage × depth × stories). If
  built, derived SF lands in its own field tagged `sf_source='derived_dimensions'`,
  never merged into the reported-SF column, and always carries the ESTIMATED label.
- `[version]` resolves to the PLUTO release string recorded at retrieval (the
  `pluto_dataset_version` provenance already carried on each matched parcel).

## Deliverable status

Spec complete. Build deferred to Phase 5 per roadmap (UI built last, after the math is proven in Phase 4–5 validation).
