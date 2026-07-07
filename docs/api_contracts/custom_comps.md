# Custom-comps contract — DRAFT v1 (not implemented)

`contract_version: 1.0.0` · `product: "custom_comps"` · route `POST /api/v1/custom_screen`

The user supplies their **own** list of comparable BBLs; the tool runs the same distribution /
percentile / variance math on exactly that set — **without any comp-selection safeguards** — and
stamps the result "user-provided, not screened by the tool's selection logic." This is the manual
counterpart to the auto-screen: the user owns comp choice, the tool owns the math and the
provenance.

## Why the stamp is load-bearing

The auto-screen's credibility comes from its **selection safeguards**: same size band (±50/75% SF),
distance cap, building-class/subcode match, and a hard refusal below the 8-comp minimum. A
user-provided set has **none** of those guarantees — the comps can be any size, any distance, any
class, any count. So "safeguards not applied" cannot be an implicit assumption the reader has to
know; it must be an **explicit response field** and a visible stamp. The tool computes honest
statistics over whatever set it's given and refuses to imply those numbers carry the auto-screen's
comparability guarantees.

## Request

```jsonc
POST /api/v1/custom_screen
{
  "subject_bbl": "1013010001",        // required. 10-digit BBL of the subject parcel.
  "comp_bbls": [                      // required. 1..N user-chosen comp BBLs (10-digit).
    "1013010033", "1012770027", ...   // dedup applied; subject_bbl removed if present.
  ],
  "contract_version": "1"             // optional; server pins to major 1.
}
```

Notes:
- **No radius / band / class parameters** — selection is fully user-driven, so there is nothing to
  tune. Any such fields, if sent, are ignored (documented, not silently honored).
- Address input is out of scope for v1 of this contract; the frontend resolves address→BBL up front
  and sends BBLs.

## Response (success) — `status: "ok"`

Reuses the **entire** `/api/screen` success envelope (so the frontend renders it with the same
components), and **replaces the selection-metadata block with a `comp_source` block**. Fields:

```jsonc
{
  "status": "ok",
  "product": "custom_comps",
  "contract_version": "1.0.0",
  "disclaimer": "…",                    // same global disclaimer string
  "subject": { …subject panel… },       // identical shape to /api/screen (roll + PLUTO fields, cited)

  "comp_source": {                      // NEW — replaces comp_meta.composition/safeguard fields
    "type": "user_provided",
    "selection_safeguards_applied": false,          // <-- the explicit, non-optional flag
    "stamp": "Comparables are user-provided and were NOT screened by the tool's selection logic: no size band, no distance cap, no building-class match, and no minimum-count enforcement were applied. The statistics below describe this exact set as given.",
    "requested_count": 12,              // len(unique comp_bbls after cleaning)
    "resolved_count": 11,               // how many resolved to a usable parcel
    "unresolved_bbls": [                // BBLs dropped, with why — never silently discarded
      { "bbl": "1099990001", "reason": "not_found_in_roll" },
      { "bbl": "1000380001", "reason": "non_positive_market_value" }
    ],
    "min_for_stats": 3,                 // below this, percentiles suppress (see below); NOT a refusal
    "distance_miles_max": 4.2           // FYI only (max subject→comp distance); not a cap, not a filter
  },

  "signals": [ … ],                     // SAME three signals as auto-screen (see "Signals" below)
  "comps": [ … ],                       // SAME comp-row shape as the variance table, minus safeguard semantics
  "provenance": { … },                  // same citations block
  "context": { … }                      // same static context
}
```

### Signals

Identical shape to the auto-screen's `signals[]` (`assessed_value_market`, `tax_bill`,
`mv_per_gross_sf`): each has `n`, `mean`, `median`, `minimum`, `maximum`, `stddev`,
`subject_value`, `subject_percentile`, `dispersion`, `distribution[]`, `comp_points[]`, display
strings, plus `refused`/`refusal_reason`. Two differences in **meaning** (not shape):

- **No `radius_used_miles`, no `sf_band_*`, no `exact/adjacent composition`, no `low_exact_caution`**
  in `comp_meta` — those describe selection, which didn't happen. They are **absent**, and
  `comp_source.selection_safeguards_applied: false` stands in their place. The frontend must not
  render "size band" / "exact match" chrome for this product.
- **Percentile suppression by count**: if `resolved_count < comp_source.min_for_stats`, each
  signal returns `subject_percentile: null` with a `percentile_note` ("Percentile not shown: fewer
  than N user-provided comps.") — the distribution still renders for context. This is a **display
  suppression, not a refusal** (unlike auto-screen, which refuses below 8). A user may deliberately
  compare against 2 comps; the tool shows the diff, just not a percentile.

### Stats-layer caveats that STILL apply (metric integrity, not selection)

These are properties of the **metric**, not of comp selection, so they still compute and disclose:
- **Per-SF size-comparability**: the `mv_per_gross_sf` percentile still restricts to size-comparable
  comps and discloses when few qualify (same rule as auto-screen). Rationale: this is about whether
  a per-SF number is meaningful, independent of who chose the comps.
- **Land-dominant exclusion** from per-SF (PLUTO BldgArea/LotArea < 0.30): still excludes such comps
  from the per-SF calc and discloses, since a land-dominant parcel's per-building-SF is meaningless
  regardless of selection.
- **Non-positive / tax-exempt comps** are dropped and reported in `unresolved_bbls` (a $0-value comp
  can't sit in a value distribution).

## Refusals

```jsonc
{ "status": "refused", "reason": "...", "message": "...", "product": "custom_comps", "subject": {…|null} }
```
- `subject_not_found` — subject BBL not in the roll.
- `subject_tax_exempt` — subject has non-positive market value (no basis to compare).
- `no_valid_comps` — every supplied comp BBL was unresolved (0 usable). Names the count and reasons.
- Note: there is **no `insufficient_comps_within_cap`** and **no 8-comp refusal** — count is the
  user's choice; below `min_for_stats` we suppress percentiles, not refuse.

## Reuse vs new

**Reuses (unchanged):**
- Subject resolution / validation (`geocode._validate_bbl`) and the subject panel.
- `CompRow` / `CompSet` data structures.
- `stats.compute_stats`, `variance.compute_variance`, and `serialize.build_screen_view` assembly
  (signals, distributions, comp_points, citations, provenance) — fed a pre-built CompSet.
- The per-SF size-comparability and land-dominant stats-layer logic.
- Citation / provenance plumbing.

**New (must build):**
- Endpoint `POST /api/v1/custom_screen`.
- A **`select_from_bbls(subject_bbl, comp_bbls)`** builder that constructs a `CompSet` **directly**
  from the given BBLs — pulling each comp's roll + PLUTO fields — and **bypasses `select_comps`**
  entirely (no size band, no radius sweep, no class/subcode match, no min-count gate). This is the
  core new piece and the one place the "no safeguards" property lives.
- Per-comp resolution reporting (`resolved_count`, `unresolved_bbls` with reasons).
- The `comp_source` block + the `selection_safeguards_applied` flag + the stamp string.
- Serializer branch that emits `comp_source` in place of the selection `comp_meta`, and omits
  radius/band/exact-match chrome.

## How it MUST differ from auto-screen (summary)

| Property | Auto-screen | Custom-comps |
|---|---|---|
| Who picks comps | tool (`select_comps`) | user (`comp_bbls`) |
| Size band (±50/75% SF) | enforced | **not applied** |
| Distance cap / radius | enforced | **not applied** (max distance shown, FYI) |
| Class / subcode match | enforced | **not applied** |
| 8-comp minimum | **refuses** below | suppresses percentile below `min_for_stats`, no refusal |
| Safeguard disclosure | implied by product | **explicit `selection_safeguards_applied: false` + stamp** |
| Stats/variance math | same | same |
| Provenance | same | same |

The single hard rule: **the "not screened by the tool's selection logic" status is a first-class,
always-present response field (`comp_source.selection_safeguards_applied` + `comp_source.stamp`),
never an assumption the reader must infer.**
