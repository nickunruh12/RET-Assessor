# Backlog / Roadmap (deferred)

Post-v1 work, revisit **after v1 office + retail is locked and presented**. Nothing here is
committed scope; each item carries its gate. Sequencing and locked build-order live in
DECISIONS.md ("Build-order sequence"); this file is the deferred-work register.

## 1. Other main class-4 asset types (industrial, warehouse, garage, …)

Engine extensions in the existing screener (same CompRow/CompSet/stats/serialize path, same
provenance and no-verdict discipline), one asset type at a time:

- **Tuned comp criteria per class group** — each asset type gets its own bucketing, SF band,
  and radius caps, the way office and retail each do.
- **Per-class Phase-2 fill-rate kill-gate BEFORE building** — measure the source fill rates
  (value, SF, coordinates, and any use-mix fields the class needs) against NYC Open Data first;
  if the data can't support an honest screen, the type does not get built (the retail/condo
  precedent: measure, then decide). No engine code until its gate clears.
- Each goes live via its own upstream interception branch in `_screen_view` keyed on class
  prefix — NOT by loosening the resolver scope gate (see DECISIONS.md scope-gate entry).

## 2. Vacant development-site module (SEPARATE module, not an engine extension)

A land-comping module distinct from the building screener:

- **Value per buildable SF, zoning-district match** — land is comped on buildable area and
  zoning, not on building attributes; this is a different comp model, hence a separate module.
- **Detected route, measure-don't-declare** — a class-V / zero-BldgArea parcel **auto-routes**
  to the land module and discloses that it did. Routing follows physical reality: vacant →
  land module; has-building → building screener. The user never declares building-vs-land.
- **Until built, a class-V parcel returns a clean "not yet supported" refusal**, never a dead
  or silent route.
- **Explicitly NOT a v1 gap:** "screen an occupied parcel *as* a redevelopment site" (i.e.
  ignore the existing building and value the land under it) is a **separate future feature**,
  not a missing v1 capability. The buildable-SF path is independent of the land module.

## 3. Commercial condos — revisit (soft backlog, OPEN question)

Explore further **after** the other asset types are built. This is an open question, **not a
sealed closure.** The measured three-path findings (building-level dead on value; unit-level
value-aggregation rejected on comparison integrity; unit-level direct dead on comparability
data, including the storefront-registry check) are recorded in detail in KNOWN_LIMITS.md. Revisit
if a new public data source exposes intra-building retail-unit comparability attributes (floor,
corner-vs-inline, frontage, grade), or if the aggregation-integrity trade-off is reconsidered.

## 4. Specific remaining class-4 asset types (each gated, deferred until after v1 ships)

Section 1 states the general discipline; these are the specific classes and their per-class
caveats. **Industrial (`F*`) is NOT here** — it is the immediate post-v1 candidate in the locked
build sequence (see DECISIONS.md "v1 completion scope"), pending its fill-rate kill-gate.
Everything below is deferred until after v1 ships, and each needs its **Phase-2 fill-rate
kill-gate FIRST — build only if it clears.**

- **Garages / parking (`G*`)** — class-4, buildable, niche. Own fill-rate gate before building.
- **Hotels (`H*`)** — class-4, but value is **income / RevPAR-driven**, so assessed-value-per-SF
  comp logic may fit poorly. Needs its own fill-rate gate **plus a comp-basis check** (does
  per-SF even describe hotel value?) before building.
- **Loft buildings (`L*`) and the misc commercial class-4 long tail** — buildable, niche,
  deferred. Own gates.

Discipline is uniform: **Phase-2 fill-rate kill-gate FIRST, build only if it clears** (the
retail / commercial-condo precedent — measure against source data before any engine code).
