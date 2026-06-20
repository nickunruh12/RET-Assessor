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

**2026-06-19 — Derived-dimensions SF tier MEASURED and REJECTED.** Tested recovering gross building area as `bld_frt × bld_dep × bld_story` for the 37,101 class-4 parcels with no reported gross area. Result: only **659 candidates** have all three dimensions populated and non-zero, and **87% (574) are class-R condo unit lots** where the formula returns the whole-building envelope, not the unit (validation median ratio 8.4× overstatement — e.g. BBL 1009941303, a 1460 Broadway condo unit, derives 186,224 SF = the entire 16-story building). The genuinely valid remainder is **~85 parcels** (mostly 1-story garages), worth **+0.06pp** of coverage. Formula accuracy even where valid is only moderate (unbiased at the median but ±25% on ~67% of parcels, degrading with floors — setbacks, partial top floors, irregular footprints). **Decision: do NOT build the derived tier.** The +0.06pp recovery does not justify a whole estimation tier or the condo-overstatement risk. **$/SF coverage is therefore capped at reported gross building area** (PLUTO `BldgArea` primary, roll `gross_sqft` fallback) = **71.8%** (94,663 / 131,764). Parcels with no reported gross area (the persisted `parcels_no_sf` table, 37,101 rows) hit the per-signal $/SF refusal and still receive the assessed-value and tax-bill distributions.

---

## RESOLVED (2026-06-19)

- **[RESOLVED] Roll snapshot / vintage.** Ship on `curmkttot` — confirmed current with the FY2027 FINAL roll, no lag vs DOF. The earlier "swap to `finmkttot` later" plan is moot; `cur` already reflects final.
- **[RESOLVED] Ground-truth cross-check.** PASSED 5/5 to the dollar against the official DOF lookup (see dated entry above). Accuracy gate closed.

## OPEN decisions — not yet locked

- **[LOCKED 2026-06-19] Minimum comp count for refusal gate = 8.** See dated lock above; tunable in Phase 4.
- **[LOCKED 2026-06-19] Comp SF band = ±50%.** See dated lock above; tunable in Phase 4.

_(No remaining open decisions.)_
