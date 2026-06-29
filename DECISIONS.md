# DECISIONS.md

Every irreversible choice, dated, with reason. Append-only.

---

**[LOCKED] User / persona.** Tool serves the **CRE underwriter sanity-checking a tax basis**, not the property owner. Every design choice resolves in the underwriter's favor: provenance over persuasion, a distribution over a verdict, an input set that runs from a deal's address alone.

**2026-06-19 — Jurisdiction and scope locked.** NYC only, tax class 4 (commercial) only, v1. Architecture jurisdiction-agnostic (second metro = new plugin file, not a rewrite). No second metro until NYC passes every kill gate.

**2026-06-19 — Three-layer separation locked.** SIGNAL (public, deterministic, no LLM) / CONTEXT (display-only, cited) / RUNG 3 (opt-in NOI-based implied cap rate, off by default). The honesty line: a user-supplied number must never be confusable with a public one, and no LLM ever touches the math path.

**2026-06-19 — Primary assessment dataset = `8y4t-faws`.** Canonical DOF roll covering all four classes; alternates are subsets/older cuts. Confirmed via data.gov catalog + NYC Open Data, 2026-06-19.

**2026-06-19 — Physical-characteristics source = PLUTO `64uk-42ks`.** Source of `BldgArea`, `BldgClass`, `LotArea`, `YearBuilt`, neighborhood. Record exact version string at retrieval.

**2026-06-19 — Class 4 assessment ratio = 45% of market value.** Basis for value-field reasoning. Re-cite directly to DOF "Determining Your Assessed Value."

**2026-06-19 — FY2026 Class 4 tax rate = 10.848%.** CONTEXT only. Confirm exact figure against the DOF official tax-rate table before display.

### Verified live against SODA, 2026-06-19

**`8y4t-faws` is the full multi-year roll. Loader filters by `year`.** Class 4 = 1,303,243 rows all-years; 263,023 for `year='2027'` (latest, FY2027 tentative). One source covers the YoY-spike SIGNAL; no second dataset needed.

**Column names locked from live introspection.** tax class=`curtaxclass`, year built=`yrbuilt`, building class=`bldg_class`, ZIP=`zip_code`, BBL=`parid`, SF=`gross_sqft`. Value snapshots: `cur`/`fin`/`ten`/`py`/`cbn` × `mkttot`/`acttot`/`trntot`/`txbtot`.

**VALUE FIELD LOCKED: `curmkttot`** (current market value total) is the comparison basis; switch to `finmkttot` when the final roll publishes (`finmkttot`=0 on the tentative roll). Tax bill = `curtxbtot` × class-4 rate. Never mix snapshots or market/assessed/transitional across comps. `curacttot` is mechanically 0.45×`curmkttot`, so market value is the only non-redundant value field.

**Vintage DEMOTED to display-only.** `yrbuilt` fill = 68.1% on class 4 (FAIL ≥80% gate). Not reliable enough to be a comp criterion.

**Gross-building-area source = PLUTO `BldgArea`.** The SF metric throughout this tool is **gross building area** (PLUTO `BldgArea`), not usable/rentable area. 99.98% fill on commercial (O*/K*) vs 71.8% for roll `gross_sqft`. `gross_sqft` (also a gross-building-area figure, from the DOF roll) is the fallback when the PLUTO join misses.

**Assessment-ratio-vs-45% SIGNAL REMOVED; replaced by two SIGNALs (Nick's call, 2026-06-19).** (1) **Market-value-per-gross-building-area percentile** = `curmkttot ÷ BldgArea` ranked against the comp set, where the denominator is PLUTO `BldgArea` (gross building area). (2) **Phase-in gap** = `curtrntot` vs `curacttot`, showing how much of an assessment increase is still being phased in. Both deterministic, public, no verdict. The old ratio is mechanically 0.45 for every class-4 parcel and carries zero information. **Framing discipline:** this $/SF figure is a **peer-comparison screen** (where does this parcel's market-value-per-gross-SF sit against its comps), NOT a reconstruction of the assessor's valuation method — DOF values class 4 primarily by income (capitalized net operating income), not by $/SF. The SIGNAL screens for outliers among peers; it does not claim to reproduce how the assessment was set.

**2026-06-19 — Ground-truth check PASSED 5/5. Accuracy gate CLOSED.** Manually verified 5 class-4 parcels against the official DOF property lookup (a836-pts-access.nyc.gov); API `curmkttot` matched DOF published market value exactly, to the dollar, on all 5:
- 438 Greenwich St — BBL 1002230035 — API 1,700,000 / DOF 1,700,000 — MATCH
- 646 East 12 St — BBL 1003940032 — API 2,578,000 / DOF 2,578,000 — MATCH
- 356 West 12 St — BBL 1006400041 — API 4,820,000 / DOF 4,820,000 — MATCH
- 4 Doyers St — BBL 1001620044 — API 1,740,000 / DOF 1,740,000 — MATCH
- 171 Christopher St — BBL 1006360033 — API 1,158,000 / DOF 1,158,000 — MATCH

**2026-06-19 — API is current with the FY2027 FINAL roll. No vintage lag vs DOF.** DOF labels these parcels "2026-2027 Final" and `curmkttot` matches that final figure exactly. Supersedes the earlier open item that flagged a possible API-vs-DOF lag — that assumption was wrong. Ship on `curmkttot`; it reflects the final roll.

**2026-06-19 — Tax-bill SIGNAL basis LOCKED = `curtxbtot` (transitional taxable) × FY2026 class-4 rate 10.848%. NEVER `curacttot`.** DOF pages show three distinct values: ESTIMATED MARKET VALUE (=`curmkttot`, the distribution basis), MARKET AV (=`curacttot`, the mechanical 45%), and TRANS AV labeled "Your 2026/27 Taxes Will Be Based On" (=`curtxbtot`, the transitional taxable). Taxes are levied on the transitional taxable, lower than actual assessed during phase-in. Worked example: 438 Greenwich — actual assessed 765,000 vs transitional taxable 709,500. Using `curacttot` would overstate every tax bill.

**2026-06-19 — Minimum comp count LOCKED = 8.** Below 8 comps in a target's comparison set → visible refusal, regardless of how many optional fields were supplied. Starting value (roadmap default); tunable in Phase 4 validation once real comp-set sizes are observed.

**2026-06-19 — Comp SF band LOCKED = ±50%.** A parcel qualifies as a comp when its gross building area is within ±50% of the target's gross building area (PLUTO `BldgArea`, `gross_sqft` fallback). Starting value (roadmap default); tunable in Phase 4 validation.

**2026-06-19 — Terminology LOCKED = "gross building area."** The SF metric is everywhere called **gross building area** (PLUTO `BldgArea`; roll `gross_sqft` as fallback — also gross), never "usable" or "rentable" square feet. The market-value-per-SF SIGNAL is a **peer-comparison screen**, not a reconstruction of the assessor's method: DOF values class 4 primarily by income (capitalized NOI), so $/gross-SF is used only to rank a parcel against its comps, never to claim how the assessment was derived.

**2026-06-19 — $/SF output contract LOCKED (recorded; rendering deferred).** Every market-value-per-gross-building-area figure must display its denominator's source, tied to the row's `sf_source` tag, every time — no unlabeled $/SF output. Labels: `pluto_bldgarea` → "based on gross building area (PLUTO [version])"; `roll_gross_sqft` → "based on gross building area (DOF assessment roll)"; `derived_dimensions` → "based on ESTIMATED gross building area (frontage × depth × stories, not a reported figure)"; no SF from any tier → per-signal refusal "Market-value-per-SF unavailable, gross building area missing for this parcel," shown alongside the assessed-value and tax-bill distributions (which don't need SF). The label rides on the $/SF figure itself — same provenance discipline as the citation tuple. Full table in `docs/INPUT_SPEC.md`.

**2026-06-19 — v1 ACTIVATED product = Office (O*) only.** v1 scope is tax class 4 commercial only, and within it **Office (building class `O*`) is the only ACTIVATED product type at launch.** Every other class-4 commercial class (retail `K*`, industrial `F*`, warehouse `E*`, garage `G*`, loft `L*`, etc.) returns an **"out of scope for v1"** refusal until it is individually validated and activated by the same method as office (parcel-count-driven bucketing + comp-quality validation). Tax classes 1, 2, and 3 are out of scope entirely. Post-v1 expansion path recorded in `KNOWN_LIMITS.md`.

**2026-06-19 — Office class grouping LOCKED (config-driven in `comp_criteria.json`).** Office subclasses bucket as: **`O1`, `O2`, `O3`, `O4` each match EXACTLY** (own bucket, no cross-matching); **`O5`+`O6` grouped** ("office with commercial"); **`O7`+`O8`+`O9` grouped** ("misc office"). Rationale: the class code encodes building stories at 100% fill, so the common codes stay exact for tight peers, while the rarer codes are grouped to avoid comp starvation. Buckets live in `config/comp_criteria.json` and are tunable without code changes.

**2026-06-19 — Location matching = geographic distance (PLUTO lat/lon), NOT ZIP.** Comps are ranked/collected by great-circle distance from the subject's PLUTO latitude/longitude. **ZIP is demoted to an optional pre-filter only** (off by default). This supersedes the earlier `borough_and_zip` location match in the comp config.

**2026-06-19 — Radius logic LOCKED = radius-first with automatic expansion.** Collect ALL qualifying comps within **0.5 miles**; if fewer than the minimum (8), expand automatically toward a **1.0-mile hard cap**; if still under 8 at 1 mile, **REFUSE** with "insufficient comparable properties within 1 mile." No manual expand button. The **actual radius used is displayed on every result.** Min comp count = 8. Starting radii (0.5 start, 1.0 cap) and min count are tunable and logged for Phase 6 validation.

**2026-06-20 — Tiered distance-first fallback ACCEPTED as v1 comp logic.** The comp selector relaxes distance fully on the exact class (0.5→1.0 mi) before adding adjacent ladder classes; O4 and the grouped buckets (O5+O6, O7+O8+O9) are exact-or-refuse. Validated on the full office census (7,160 subjects): **31.8% refusal** (−4.7pp vs the 36.5% exact baseline), matching grouped coverage *by construction* but preserving the exact-vs-adjacent distinction instead of blending classes. Fallback is a **targeted rescue, not wholesale loosening**: 93.0% of the 4,884 successful sets stay fully exact-class; only 340 subjects (7.0%) use fallback, concentrated in the Bronx/Queens. Every comp row carries `match_type` (exact|adjacent) + its class. See `docs/COMP_VALIDATION.md`.

**2026-06-21 — RUNG 3 (user-NOI implied cap rate) LOCKED: opt-in, fenced, no verdict.** RUNG 3 is the ONLY place a user-supplied number enters the tool, so the entire design is fencing it off from public data. (1) **Off by default** — runs only when explicitly enabled (a toggle/flag), never in the standard output. (2) **Computes ONE number**: implied cap rate = subject DOF market value (`curmkttot`) ÷ user NOI. No comparison rate, no "market cap rate," no high/low, no verdict — the user judges whether the rate looks aggressive. (3) **Stamped user-supplied**: every output reads "based on the NOI you provided"; framing is possessive ("your NOI implies X%", never "the cap rate is X%"). The NOI carries NO citation (it is not public); the market value carries its roll citation tuple. (4) **Partitioned**: the result is a structurally separate object, never blended into the public SIGNAL outputs (assessed-value, tax-bill, $/SF, variance), so a user-derived number can never be mistaken for a public one. (5) **Guardrails**: NOI must be a positive number — zero/negative/non-numeric is rejected with a clear message, never computed; a tax-exempt subject (`curmkttot <= 0`) cannot run RUNG 3 (returns the existing no-comparison message, never divides). No LLM, pure arithmetic. **WHY it must be user-input**: the assessor's actual NOI comes from RPIE (Real Property Income & Expense), which NYC does **not publish per parcel**, so it cannot be auto-pulled — that data dependency is exactly what keeps RUNG 3 honest.

**2026-06-20 — Non-positive market value EXCLUDED from the comp universe (tax-exempt parcels are not assessment peers).** Any parcel with `curmkttot <= 0` (and the degenerate null case) is tax-EXEMPT — no positive market value — and is excluded from the comp universe entirely, by the same categorical logic as the condo exclusion. Routed to the persisted `exclusions` table with reason code `NON_POSITIVE_MARKET_VALUE` and counted (29 office parcels citywide; 0 nulls). Rejected alternatives: keeping them (distorts every distribution with a known-wrong inclusion — pulled `min` to 0) and a per-signal stats-only drop (these parcels should never be a comp for anything). **A SUBJECT with `curmkttot <= 0` gets a no-comparison refusal** — note `subject_tax_exempt`, message "this parcel has no positive market value (tax-exempt); assessment comparison does not apply" — parallel to the out-of-scope refusal for non-office. Config flag `exclude_non_positive_market_value` (default true).

**2026-06-20 — Low-exact CAUTION flag LOCKED (warn, never refuse).** When a successful comp set has **fewer than 3 exact-class comps**, the output attaches a visible caution ("comp set is largely adjacent-class, interpret accordingly"). It does NOT refuse — it warns. The descriptive philosophy stands; the label protects the user. Distinct from the per-signal/min-count refusals, which are hard. Threshold (3) is tunable, logged for Phase 6.

**2026-06-19 — Derived-dimensions SF tier MEASURED and REJECTED.** Tested recovering gross building area as `bld_frt × bld_dep × bld_story` for the 37,101 class-4 parcels with no reported gross area. Result: only **659 candidates** have all three dimensions populated and non-zero, and **87% (574) are class-R condo unit lots** where the formula returns the whole-building envelope, not the unit (validation median ratio 8.4× overstatement — e.g. BBL 1009941303, a 1460 Broadway condo unit, derives 186,224 SF = the entire 16-story building). The genuinely valid remainder is **~85 parcels** (mostly 1-story garages), worth **+0.06pp** of coverage. Formula accuracy even where valid is only moderate (unbiased at the median but ±25% on ~67% of parcels, degrading with floors — setbacks, partial top floors, irregular footprints). **Decision: do NOT build the derived tier.** The +0.06pp recovery does not justify a whole estimation tier or the condo-overstatement risk. **$/SF coverage is therefore capped at reported gross building area** (PLUTO `BldgArea` primary, roll `gross_sqft` fallback) = **71.8%** (94,663 / 131,764). Parcels with no reported gross area (the persisted `parcels_no_sf` table, 37,101 rows) hit the per-signal $/SF refusal and still receive the assessed-value and tax-bill distributions.

---

## RESOLVED (2026-06-19)

- **[RESOLVED] Roll snapshot / vintage.** Ship on `curmkttot` — confirmed current with the FY2027 FINAL roll, no lag vs DOF. The earlier "swap to `finmkttot` later" plan is moot; `cur` already reflects final.
- **[RESOLVED] Ground-truth cross-check.** PASSED 5/5 to the dollar against the official DOF lookup (see dated entry above). Accuracy gate closed.

## OPEN decisions — not yet locked

- **[LOCKED 2026-06-19] Minimum comp count for refusal gate = 8.** See dated lock above; tunable in Phase 4.
- **[LOCKED 2026-06-19] Comp SF band = ±50%.** See dated lock above; tunable in Phase 4.

_(No remaining open decisions.)_

## Build-order sequence (LOCKED 2026-06-29)

Fixed so the sequence isn't re-litigated. Do steps in order; do not pull later steps forward.

1. **(done) Office-only UI builds** — hover property info on chart markers, and type-agnostic
   chart polish. Both shipped this commit, office-only and product-type-agnostic.
2. **(next) Second property type** — expand to whichever non-office class-4 type is easiest
   from the data (retail, industrial, …), one type at a time, each with its own validation
   pass. This comes **before** the larger UI rebuild so the layout meets a second product
   type while restructuring is still cheap.
3. **(later, after property-type expansion) Larger UI builds** — held deliberately until the
   layout has met multiple property types:
   - Map view toggle (subject + comps as locations; **no mean/median markers** — they aren't
     locations).
   - Hover property info in map view (address, distance, phase-in gap, **and all three
     metrics** per parcel, since the map isn't tied to one chart's metric).
   - Welcome/title page: overview of what the tool does + the **autogenerate-screener vs.
     user-provided custom-comp-list** fork. The custom path bypasses the 8-comp minimum and
     radius rules and MUST carry a prominent, visually distinct "comps user-provided, not
     screened; minimum-comp and radius safeguards do not apply" stamp — designed in from the
     first commit so a hand-picked result is never mistaken for a screened one.
   The **custom-comp path is deferred specifically because its comp-selection interface is
   property-type-dependent** (a comp picker must reason about each comp's type once more than
   one type exists); building it pre-expansion would mean building it twice.
