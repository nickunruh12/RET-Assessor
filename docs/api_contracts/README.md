# API contracts (reference specs — not yet implemented)

Stable, versioned request/response contracts for planned backends, written **before**
implementation so a future frontend (e.g. Replit) can build against a fixed shape. These are
**documentation only** — no engine code exists for them yet. When a backend is built, its
implementation must match the contract here, or the contract is revised **and versioned** first.

## Contracts

| Contract | Route (proposed) | Status | File |
|---|---|---|---|
| Custom comps | `POST /api/v1/custom_screen` | v1 implemented (dev, 2026-07) | [custom_comps.md](custom_comps.md) |
| Land valuation | auto-routed via `/api/screen` (class-V) | DRAFT v1 — blocked on a data kill-gate | [land_valuation.md](land_valuation.md) |
| Class-2 route | auto-routed via `/api/screen` (plain-'2' C/D) | DESIGN — capped-subclass refusal LOCKED (DECISIONS.md 2026-07-16) | [class2_route.md](class2_route.md) |

## Versioning policy

- Each contract carries a `contract_version` (semver). The route is version-pinned (`/api/v1/…`).
- **Additive changes** (new optional response field) → minor bump, same route.
- **Breaking changes** (rename/remove a field, change a type, change required request fields) →
  major bump **and a new route** (`/api/v2/…`); the old route keeps its shape until retired.
- The frontend pins to a major version. A field, once documented at a version, does not change
  meaning within that major version.

## Shared conventions (inherited from the live `/api/screen`)

Both contracts reuse the existing screen response envelope, so these hold everywhere:

- **No verdicts.** No field ever says good/bad, over/under-assessed, cheap/expensive. Outputs are
  distributions, percentiles, and attribute diffs. The banned-word discipline (`render_check`)
  applies to every string these backends emit.
- **Provenance over persuasion.** Every number traces to a public source field or a user input.
  Each row/figure carries or references a citation (`source_dataset`, `roll_year`, field name).
  User-supplied numbers are stamped "user-provided (no citation)".
- **Refusal shape** (any product): `{ "status": "refused", "stage": "...", "reason": "...",
  "message": "...", "disclaimer": "...", "subject": {...|null} }`. Refusals are explicit messages,
  never blanks or a fabricated screen.
- **Success envelope** (any product): `status: "ok"`, plus `disclaimer`, `subject`, `signals[]`,
  `provenance`, `context`, and product-specific blocks. See each contract for the product's
  additions.
- **`product` field.** Every success response names its product: `"office" | "retail" |
  "industrial" | "custom_comps" | "land"`. The frontend switches rendering on this.

## What these are NOT

- Not an implementation, not a schema migration, not engine changes.
- Not a promise of a ship date. Land valuation in particular is gated on a data measurement
  (see its kill-gate) that may come back negative, in which case the contract is shelved, not built.
