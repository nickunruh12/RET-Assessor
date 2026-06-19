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
| Confirmation of SF | Corrects stale PLUTO `BldgArea` |
| Vintage (year built) | Tightens comp band *if* Phase 2 fill rate kept vintage as a criterion |

## Tier 2 — optional, CONTEXT enrichment or RUNG 3

| Field | Powers | Output discipline |
|---|---|---|
| **Purchase price + date** | Purchase-vs-DOF-market-value SIGNAL | Cited gap, no verdict: "you purchased for X on [date], DOF market value is Y, a Z% gap." Both numbers real → rung-1 arithmetic. |
| **NOI** | RUNG 3 implied cap rate | Off by default. Output stamped "based on the NOI you provided." No comparison rate, no verdict, visually partitioned from public figures. |

## Behavior rules

- Tier 0 alone → full distribution + the three public SIGNAL comparisons (assessed-value distribution/percentile, tax-bill distribution/percentile, assessment-ratio deviation vs 45%).
- Supplying Tier 2 purchase price → adds the purchase-vs-market gap SIGNAL.
- Loading two roll years (engine parameter, not a user field) → adds the YoY assessment-change-vs-comp-set SIGNAL.
- Enabling RUNG 3 toggle + entering NOI → adds the implied-cap-rate line, partitioned.
- Below the minimum comp count → visible refusal, regardless of how many optional fields were supplied.

## Deliverable status

Spec complete. Build deferred to Phase 5 per roadmap (UI built last, after the math is proven in Phase 4–5 validation).
