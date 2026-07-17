# Class-2 route — design (plain-'2' C/D rentals screen; capped subclasses refuse)

`contract_version: 0.1-draft` · Status: **DESIGN ONLY — no class-2 data is loaded; nothing here
is implemented.** The capped-subclass refusal below is a **LOCKED decision** (DECISIONS.md,
2026-07-16) recorded ahead of the build so it cannot be re-litigated when the route lands.

## Scope split (decided, measured)

| Segment | Parcels (FY2027 final) | Behavior |
|---|---:|---|
| Plain `'2'`, building class C (walk-up rental) | 18,381 | screens — full product |
| Plain `'2'`, building class D (elevator rental) | 14,815 | screens — full product |
| Plain `'2'`, building class R (condo/coop units) | 224,887 | refuses — existing condo paths |
| **`2A` / `2B` / `2C` (10 or fewer units)** | **78,952** | **refuses — `capped_subclass` reason (this doc)** |

## The `capped_subclass` refusal

- **Reason code**: `capped_subclass` (refusal shape per README — never the generic
  `not_class_4` once the subclass is identifiable, and never the plain out-of-scope message:
  this is a distinct fact and gets its own message, same principle as the condo billing-lot vs
  unit-lot split).
- **Fires on**: subject entry (auto path and custom-comps subject) **and** custom-comp entry
  (a 2A/2B/2C parcel entered as a user comp is excluded with the same stated reason).
- **Detection**: roll `curtaxclass ∈ {'2A','2B','2C'}`. Requires class-2 roll rows (or at
  minimum a parid → curtaxclass map) in the DB. **Unreachable today** — the loaded roll is
  class-4-only and PLUTO has no tax-class field, so these BBLs currently refuse with the
  truthful generic not-class-4 message (verified 2026-07-16: 1000070038, 1000110010,
  1000071101). No refusal code ships before the data that makes it reachable.

### Message copy — FINAL (wording approved 2026-07-16)

> Not supported: small residential buildings with 10 or fewer units (tax classes 2A, 2B, and
> 2C). For these buildings, New York State law limits how much of a property's value can be
> added to its tax bill each year — no more than 8% per year and 30% over five years — even
> when the value rises faster. Once a building's value outruns that limit, the amount it is
> billed on falls behind and can stay behind for many years. Most of these buildings are
> billed on less than half of what the standard assessment formula would produce, and the size
> of the gap depends on each building's own value history. Two similar buildings on the same
> block can carry very different tax bills simply because their values rose at different
> speeds in years past. Comparing tax bills across them would rank that gap — and say nothing
> about how each property is assessed today — so this tool does not run the comparison.

Copy constraints (locked): plain language for a reader who does not know NYC tax law; the
yearly limit is explained, never named bare ("capped") without its mechanism; no internal
vocabulary (`curtxbtot`, "billable/target", subclass jargon beyond the class labels the
reader's notice shows); banned-word discipline applies in full. The gap is attributed to the
building's **value history** — never to "how long the owner has held it" (NYC's limits do not
reset on sale; holding-period framing would be inaccurate).

### Measured basis (full numbers in DECISIONS.md)

Tax: median billable is 31–52% of the 45%-of-market target by subclass; ~70% pooled bill below
half; IQR spreads 0.23–0.44 (class 4: 0.94–0.96 medians, 0.08–0.09 spreads, none below half).
Value: YoY market-value growth clipped at exactly +20.0%/yr (p90 pinned every subclass, every
year-pair 2024→2027; 30–52% at precisely +20.0%; no published DOF source for the practice; no
clip on plain-'2' C/D or class 4). Value-only rejected: ~1% of 2A subjects sit >2x from their
peer-set median EMV/SF vs 8.4% office / 13.8% retail.

## Forward notes for the buildable route (plain-'2' C/D) — not yet designed

- Loader: `curtaxclass IN ('2','2A','2B','2C')` — `='2'` alone silently misses the capped
  subclasses (the 2A/2B/2C rows are needed even though they refuse: detection requires them).
  DB rebuild ⇒ new GitHub Release + new `SCREENER_DB_SHA256`.
- Class-2 tax rate: separate line on the same DOF Property Tax Rates page already cited for
  the class-4 rate; read the exact figure at config-lock time.
- Disclosure layers measured 2026-07-16: J-51/MCI/GCCA abatements identifiable per-BBL via the
  existing ICAP mechanism (`rgyu-ii48`; J-51 on 9.3% of C / 15.6% of D). Exemption amounts
  (421-a, 485-x, J-51 exemption) are per-parcel roll fields (`curtxbextot`; 24.7% of C / 51.0%
  of D carry one); program names require one new loader (`muvi-b6kx`, Property Exemption
  Detail). Statutory-bill convention (plot `curtxbtot × rate`, disclose benefits) carries over
  from class 4.
- taxable_series is hard-filtered to tax class 4 and needs widening for class-2 subjects.
