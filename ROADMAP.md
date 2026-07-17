# NYC Class-4 Assessment Screener — Roadmap (living)

**Status:** live in production · custom-comps built on `dev`, pending merge
**Live:** https://ret-assessor.onrender.com (Render free tier; DB hosted as a GitHub Release,
verified at boot via a sha256 integrity check — `SCREENER_DB_SHA256`)
**Branches:** `main` = live/frozen (deploys on push) · `dev` = build branch · a pre-commit hook
blocks direct `main` commits · merging `dev` → `main` is the go-live act
**History:** this doc describes where the tool IS and where it is GOING. The why behind every
locked choice lives in `DECISIONS.md`; what the tool refuses to do and why lives in
`KNOWN_LIMITS.md`. This doc does not re-litigate either.

---

## The spine (unchanged, and not negotiable)

- **Every number on screen traces to either a published public field or a value the user typed
  in.** Nothing in between is invented. If the tool cannot cite it or the user did not supply it,
  the tool does not say it.
- **No verdicts.** No tool-asserted market cap rate, no true-value or over-assessment claim, no
  "you should appeal." The tool returns a distribution to read, not a conclusion. If a feature
  needs a tool-supplied number to reach a conclusion, the feature is wrong.
- **Refusal is a feature.** Below the comp minimum, outside scope, or on unusable data, the tool
  visibly refuses with a stated reason — never a padded or silently degraded answer.
- **Measure before building.** Every new asset type or data-dependent module passes its own
  kill-gate (fill rates, comp density, ground-truth spot-checks) before code is written. A gate
  that fails means the module is shelved and the measurement recorded, not worked around.
- **No LLM in the data or math path.** Deterministic end to end.

---

## Current state

**Public v1 (live on `main`):** NYC tax-class-4 **office (O), retail (K), industrial (pooled
E+F)** — each with the full provenance, disclosure, and suppression machinery. Industrial pools
the eight warehouse/factory subcodes (E1,E2,E9,F1,F2,F4,F5,F9) into one route (the E/F split is
a DOF filing artifact, measured); E7 self-storage is a walled "Self-Storage" branch inside it.
Every other class refuses with a stated reason (commercial condos get their own explanation).
(Pooled E+F built on `dev` 2026-07-17, pending merge.)

**Built and live:**
- **Comp engine** — comps selected by MEASURED property type (never a user dropdown), size band
  (office/retail ±50%, industrial ±75%; E7 self-storage no band — size is a non-driver there),
  and location (radius ladder with per-type caps). Industrial uses a shortfall-triggered
  extended radius (1.75→4.0 mi at the same band, then refuse) instead of a size threshold — the
  big-box citywide branch and the Manhattan branch were removed (measured 2026-07-17). 8-comp
  refusal gate; land-dominant comps (coverage < 0.30) excluded from per-SF and disclosed; per-SF
  percentile suppression on thin or size-dispersed sets; large-format retail (K8) keeps its
  "few true peers — directional" handling.
- **Provenance layer** — every figure cites the DOF roll (`8y4t-faws`, FY2027 final) and PLUTO
  (`26v1`) with dataset version and retrieval date; user-supplied numbers (NOI, opex) are stamped
  user-supplied, no citation; ICAP abatements disclosed, never computed with.
- **Radius override** — the slider bounds HOW FAR the tool searches; the quality logic (bands,
  class match, refusal gates) always still applies within it. Citywide resolutions beyond the
  slider max are stated as text, never a pegged thumb.
- **Welcome page + mode router** — two named modes (`auto_generate`, `custom_comps`); property
  type is always measured from the parcel.

**Built on `dev`, not yet merged — custom comps (the manual-override lane):**
- User supplies the comp list; the tool runs the same stats/variance/provenance machinery and
  labels the set, unmissably, as **not screened by the selection logic**.
- Per-comp validation **on entry** (address or BBL): not-class-4 / condo-unit / billing-lot /
  lot-range / no-coordinates exclusions each get their own truthful reason; cross-type and
  size-dissimilar comps are kept and labeled, never silently dropped.
- **Hybrid auto-fill:** below 8 valid comps the user chooses — run thin (flagged) or fill to 8
  with tool-selected, subject-matched comps; every comp carries an origin label
  ("user-supplied" / "tool-selected") and the mix is stated.
- **Cross-type composition disclosure:** whenever any cross-type comp is present, the set-level
  mix is stated ("8 comps: 7 office, 1 cross-type") — a count, deliberately no threshold.
- **Out-of-scope subjects** (e.g. hotels): accepted with a scope notice naming exactly which
  calibrated thresholds are borrowed; auto-fill disabled (no selection engine to borrow).

---

## What's next (in order)

### 1. More property types — hotels (H-codes) first
Each new type gets its own kill-gate BEFORE building: value/SF fill rates, comp density at
realistic radii, subcode structure, any type-specific data traps. Hotels are the likely next
candidate — custom-comps already accepts them as subjects (with the borrowed-threshold
disclosure), which is both demand signal and a head start on the disclosure work. No hotel
engine code until the gate passes.

### 2. Land valuation — BLOCKED ON DATA
The screen for vacant land (class-V; **8,118** class-4 V-code parcels currently refuse as
out-of-scope) needs **value-per-buildable-SF**, and the DB has `pluto_lotarea` but **no zoning
district and no FAR** — so buildable SF is uncomputable today. Do not start engine work until
the data is sourced and the kill-gate passes. The full contract, the degraded lot-SF-only
fallback, and the gate thresholds are locked in `docs/api_contracts/land_valuation.md`.

### 3. Frontend rebuild (Replit)
NYC Geosearch address autofill, map view, improved visual design. The API passed a completeness
audit: **every disclosure, citation, suppression reason, and flag is a structured JSON field**,
so a new frontend can render the full honesty layer from JSON alone. Two standing rules:
- **Wall the frontend tool to the frontend.** It never touches `comps.py`, `stats.py`,
  `serialize.py`, or any engine module. The API contract is the boundary.
- **Re-validate fidelity after the rebuild:** one parcel per asset type, confirming every
  disclosure/suppression renders — the honesty layer is the product; a frontend that drops a
  caveat is a regression even if the numbers match.

---

## Known limits / closed paths (reference — do not reopen without new data)

- **Commercial condos** — three data paths measured, all dead (no value on the billing lot; no
  unit-level comparability attributes in any public dataset). See `KNOWN_LIMITS.md` for the
  full record. Both screening paths refuse/exclude condos with specific, truthful messages.
- **E7 self-storage** — SHIPPED (2026-07-17) as a walled same-subcode-only branch inside the
  pooled Industrial route; product label "Self-Storage", refuses when it can't field 8 E7 comps.
- Appeal-outcome learning, opex-margin checks, tool-asserted cap rates, any ML/feedback loop —
  walled off (see the spine); recorded in `KNOWN_LIMITS.md` where data-gated.
- Smaller recorded limits (no-PLUTO-coordinates parcels, roll-vintage edge cases) live in
  `KNOWN_LIMITS.md`.

---

*Superseded document: `Project Notes/NYC_Assessment_Screener_Roadmap.md.docx` (the pre-build
plan; described office as an unbuilt proof-of-concept). Removed from the tree to stop it
misdirecting builds — recoverable from git history if ever needed.*
