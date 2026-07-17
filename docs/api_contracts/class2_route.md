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

## Benefit-program disclosure design — DECIDED 2026-07-16 (ships with the route)

Measured basis: peer-set comparisons on plain-'2' C/D (same letter, ±50% SF, ≤1 mi,
no-exemption peers, ≥8; clean-vs-clean control 0.98–1.00 at median position p47–p50).

- **Shelter-rent family (Article XI `5130`, 420-c `1301`, HDFC `1506/7`, UDAAP `5112`,
  DAMP `5129`, HPD `2280`): DISCLOSE ON BOTH SIDES, never refuse.** Comp badge when one
  appears in a set (~11% of the C/D universe — roughly 1 in 8 comps; does not move a set
  median). Subject-level NOTICE when the subject carries one, naming the statutory basis in
  plain language: the law values these buildings on restricted rent rather than market
  income, so their position relative to unrestricted neighbors reflects that valuation
  basis. Measured: affected C buildings sit at 0.75x their unexempt-peer median, median
  position p25, 43% below peers' 20th percentile (D: 1.02x / p52 / 22%). NOT a refusal:
  unlike the capped subclasses, the generating rule is citable statute — DOF's own
  exemption code table (`myn9-hwsy`) labels these codes "SHELTER RENT" — so the number can
  be explained rather than withheld.
- **421-a (`5110–5123`) / 485-x (`5132–5137`) / 467-m (`5124–5131`): BADGE ONLY, both
  sides.** Measured abatement-shaped — they do NOT suppress the assessment: 421-a sits at
  1.62x unexempt-peer median (p88), dropping to 1.24x when age-matched to peers built
  ≥2000, so most of the gap is new construction — real assessment variation, not program
  distortion. Payment-side fact; the ICAP convention applies. (485-x barely exists yet:
  30 parcels on C/D building classes citywide.)
- **NO SEGREGATION AND NO PROGRAM-WEIGHTING of comps.** The tax chart is abatement-neutral
  by construction: `curtxbtot` is pre-abatement (abatements exist only in `rgyu-ii48` as
  bill-stage credits) and pre-exemption (the exempt slice is the separate companion
  `curtxbextot`), so abated and unabated comps are already on the same plotted basis.
  Segregating fixes nothing and starves the pool. Comp selection stays on measured value
  drivers, never program flags.
- **The subject benefit-basis note shipped on class 4 (2026-07-16, serialize.py
  `_subject_benefit_note`) covers the class-2 route's abated/exempt subjects when the
  route lands** — same note, same statutory-basis framing; the shelter-rent NOTICE above
  is additive to it (a valuation-basis fact, not a payment-side fact).

## Forward notes for the buildable route (plain-'2' C/D) — not yet designed

- Loader: `curtaxclass IN ('2','2A','2B','2C')` — `='2'` alone silently misses the capped
  subclasses (the 2A/2B/2C rows are needed even though they refuse: detection requires them).
  DB rebuild ⇒ new GitHub Release + new `SCREENER_DB_SHA256`.
- Class-2 tax rate: separate line on the same DOF Property Tax Rates page already cited for
  the class-4 rate; read the exact figure at config-lock time.
- Disclosure inputs measured 2026-07-16: J-51/MCI/GCCA abatements identifiable per-BBL via
  the widened abatement loader (`rgyu-ii48`; J-51 on 9.3% of C / 15.6% of D). Exemption
  amounts are per-parcel roll fields (`curtxbextot`; 24.7% of C / 51.0% of D carry one);
  program names come from `muvi-b6kx` (Property Exemption Detail) + `myn9-hwsy` (code →
  program), one new loader. Statutory-bill convention carries over from class 4.
- taxable_series is hard-filtered to tax class 4 and needs widening for class-2 subjects.
