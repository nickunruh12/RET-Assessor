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

## Retail pre-launch consolidated fixes (LOCKED 2026-06-30)

From the adversarial "make-it-lie" session. These gate lifting the public `out_of_scope_v1`
refusal for K-codes (the refusal itself is NOT lifted yet).

- **Per-SF percentile is in-band-only (size-comparable).** The market-value-per-SF PERCENTILE
  number is computed on comps whose gross building area is within ±50% of the subject
  (size-comparable). With ≥5 in-band comps it is computed on those and the basis is disclosed
  (`percentile computed on N size-comparable comps`); with <5 it is SUPPRESSED with a stated
  reason. The chart, distribution, and size-dissimilar marking are unchanged — only the rank
  number. Value and tax percentiles are untouched (size dissimilarity does not corrupt them).
- **K3 (department store) per-SF percentile is always suppressed.** Confirmed the in-band rule
  does NOT subsume K3 (≈half of screenable K3 have ≥5 in-band comps), so an explicit rule
  suppresses the K3 per-SF percentile regardless of in-band count. Chart/distribution kept.
- **Suppression precedence: MIXED-USE wins over SIZE.** A parcel can trip both per-SF
  suppressors. The mixed floor-area use-blend is the deeper disqualifier (per-SF is
  meaningless regardless of comp size), so when the subject is mixed-use the per-SF signal is
  refused with the mixed-use reason and the size/in-band reason never also prints. The
  size/in-band reason prints ONLY for a clean-use subject whose per-SF percentile can't be
  computed on ≥5 in-band comps. Every suppression renders a stated reason — never a blank.
- **±1 SD band lower bound is clamped at the observed minimum.** On right-skewed pools
  mean−1 SD can go negative; a value/tax/per-SF figure cannot be negative, so the DISPLAYED
  floor is clamped at the comp set's observed minimum. The SD value and upper bound are
  unchanged.
- **Radius mode label is class-aware.** The label states what actually happened so it agrees
  with the radius-used line: K8 big-box = "Citywide — nearest big-box comps, no distance cap";
  core/specialized = "Auto — expands up to [per-class cap] mi". Office keeps the generic
  0.5–1.0 mi label.
- **Retail Expense Ratio Check mirrors office** with a 35–45% range and the verbatim "general
  rule of thumb, not a sourced benchmark" label; user-input-only, no verdict framing.
- **Tax rate is the latest-adopted rate, single config value.** `class4_tax_rate` (FY2026 =
  10.848%) is applied to the FY2027 transitional taxable value because DOF has not published
  the FY2027 class-4 rate. When DOF publishes it, update that one config value (see
  DATA_SOURCES.md maintenance note). No user-facing change.
- **K4 field-vs-note wording reconciled.** The building-class line shows the MEASURED bucket
  ("K4 (Pure retail)"); the classification note now says "K4 is DOF's mixed-use commercial
  code, but this parcel measures ≥80% retail…" so code-meaning vs measured-bucket no longer
  read as contradictory.
- **Verified (no fix): subject tax dot/percentile use the uniform statutory basis.** On
  ICAP-bearing subjects (e.g. a K8), the subject's plotted tax and percentile are
  transitional-taxable × rate (gross, statutory) — the SAME basis as every comp — so the
  comparison is apples-to-apples. The ICAP banner separately discloses the owner pays less.

## Public scope gate — "refuse unless office, OR unless K intercepted upstream" (LOCKED 2026-06-30)

The public `/screen` scope gate is now two-layered, and the next asset-type build must know both
layers:

1. **Resolver gate (`geocode._validate_bbl`)** still refuses every non-office building class with
   `out_of_scope_v1` (`if not bldg_class.startswith("O")`). This is unchanged and is what keeps
   condos (R), vacant land (V), garages (G), utilities (U), and everything else out.
2. **Upstream retail interception (`api._screen_view`)** runs AFTER resolution: a resolved
   K-code parcel (`rr.bldg_class.startswith("K")`) is routed to `build_retail_screen_view`
   instead of the office `build_screen_view`, producing the retail screen. K-codes still *resolve*
   to `out_of_scope_v1` in the resolver; the interception overrides that before any refusal
   renders.

So the effective rule is **"refuse unless office, OR unless K intercepted upstream."** A third
asset type (industrial, warehouse, …) follows the SAME pattern: it will resolve to
`out_of_scope_v1` at the resolver, and go live by adding its own upstream interception branch in
`_screen_view` keyed on its class prefix — NOT by loosening the resolver gate. Loosening the
resolver gate is the specific thing that would leak condos/vacant/garage back in (see the retail
live-switch commit), so it stays a per-class interception, never a broadened refusal.

## Below-graph label capitalization; legend/marker labels deliberately lowercase (LOCKED 2026-06-30)

- **Below-graph stat labels are capitalized tool-wide** via the single shared render path
  (`page.html` + `serialize.py`, used by both office and retail): `Subject:` / `Mean:` /
  `Median:` / `Range` (readout), `±1 SD` / `Middle 50% of comps:` / `Relative spread (CV):`
  (dispersion), `Based on gross building area (…)` (per-SF source), `Comp median:` (Phase-In
  Note), plus `Subject's Percentile:` above the chart. Presentation only; no data value or
  source identifier (`curmkttot`, `8y4t-faws`, dataset versions) was touched.
- **The chart legend + marker tooltip labels are deliberately LEFT lowercase**:
  `mean`, `median`, `comps`, `subject`, `size-dissimilar`. These strings double as **logic
  identifiers** in `app.js` (the tooltip/dataset code branches on `lab === "mean"`,
  `=== "subject"`, `=== "median"`, and builds the in-band/out-band datasets by these names).
  Capitalizing them would be a **logic change**, not a display edit, so they were left as-is
  intentionally. If they are ever capitalized, the `lab === …` comparisons and dataset-label
  construction must change in lockstep.

## Welcome/title page — design note (LOCKED 2026-06-30)

The welcome screen is **two elements only**:
1. **Intent choice — custom-comp vs. auto-generate.** Does the user want the tool to
   auto-generate the screened comp set, or supply their own custom comp list? (The custom path
   carries the prominent "comps user-provided, not screened; safeguards do not apply" stamp — see
   the build-order sequence entry.)
2. **Tool-overview message** — a short overview of what the tool does.

Explicitly **NOT** on the welcome screen:
- **No building-vs-land fork.** The tool does not ask the user whether the parcel is a building
  or a development site.
- **No property-type dropdown.** The user never selects office / retail / industrial / etc.

**Rationale — measure-don't-declare.** All property characteristics, INCLUDING building-vs-land
and asset type, are determined from parcel data AFTER address entry, never declared by the user
up front. The route (office / retail / land module / refusal) follows from the resolved parcel's
own data. This keeps the welcome page independent of the (future) vacant-land module: adding land
later changes what happens after address entry, not the welcome screen.

## v1 completion scope, build sequence, and multifamily exclusion (LOCKED 2026-07-01)

Supersedes the "v1 ACTIVATED product = Office only" scope line above (2026-06-19): retail is now
LIVE. This entry is the current v1 scope of record.

**v1 SCOPE — class-4 commercial core (three of the four institutional "food groups"):**
- **Office (`O*`) — LIVE.**
- **Retail (`K*`) — LIVE** (public `/screen`, via the upstream K-interception; see the scope-gate
  entry).
- **Industrial (`F*`) — GATE-CLEARED, APPROVED TO BUILD (2026-07-01).** Phase-2 fill-rate
  kill-gate passed (both gates; see the dated clearance entry at the end of this file). Not yet
  built; approved to build next per the sequence below.

**MULTIFAMILY IS DELIBERATELY EXCLUDED — by design, not a gap.** Multifamily rental is NYC **tax
class 2**, not class 4. The entire architecture is class-4-specific: the 45% class-4 assessment
ratio, the class-4 value fields, and the comp logic all assume class 4. Screening multifamily
would require separate class-2 logic (different ratio, different fields, different peer universe),
which is a different tool, not an extension of this one. This is a deliberate judgment call: an
investment **"food group" is not the same as a tax class**, and this tool screens **by tax class**.
Tax classes 1, 2, and 3 remain out of scope entirely.

**BUILD SEQUENCE (locked — do in order, do not pull forward):**
1. **Run the F-code (industrial) fill-rate kill-gate** — measure source fill rates before any
   build (see the REQUIRED-precondition note below).
2. **If the gate passes, build industrial as an engine extension** — same CompRow/CompSet/stats/
   serialize path, its own bucketing/SF-band/radius caps, live via its own `_screen_view`
   interception branch (never by loosening the resolver gate).
3. **Build the presentation / portfolio layer** — README narrative, differentiation paragraph,
   the commercial-condo judgment writeup, the validation story, and screenshots / a short
   recording — so the tool reads as institutional.
4. **Ship** — to professors first, then LinkedIn / resume.
5. **Remaining asset types stay backlogged** (see BACKLOG.md).

**F-CODE FILL-RATE KILL-GATE IS A REQUIRED PRECONDITION.** Industrial (`F*`) **cannot be built**
until the Phase-2 fill-rate kill-gate passes — the same measure-before-build discipline applied
to commercial condos (three paths measured against source data before any code). The gate
measures the `F*` universe's source fill rates (value, gross SF, coordinates, and any use-mix
fields the class needs) against NYC Open Data; if the data can't support an honest screen, the
type is not built. No industrial engine code before the gate clears.

---

**2026-07-01 — Industrial (F-codes) CLEARED the Phase-2 fill-rate kill-gate. APPROVED TO BUILD.**
Mirrors the retail gate discipline: measured against source data before any engine code. **Source:
NYC Open Data direct** (SODA — roll `8y4t-faws` FY2027 `period='3'` final; PLUTO `64uk-42ks`),
independent of the tool's local DuckDB.

- **Gate 1 — value fill: PASS, 99.9%.** 3,245 of 3,248 class-4 F-code parcels carry both
  `curmkttot > 0` and `curtxbtot > 0` (only 3 blanks).
- **Gate 2 — SF fill: PASS, 100%.** PLUTO `BldgArea > 0` on 3,248 / 3,248 — above the ~98%
  K-codes cleared. Per-SF denominator fully populated.
- **Population: 3,248 class-4 F-code parcels**, skewing to F5 light-manufacturing (1,365) + F4
  warehouse (844) = 68%; then F9 misc (529), F1 factory (421), F2 (73), F8 (16).

**Two NON-BLOCKING design flags to carry into the build (neither kills it):**
1. **Geographic clustering.** 84% are Brooklyn + Queens (Bklyn 1,476, Qns 1,247); only 30 in
   Manhattan. Industrial lives in dispersed outer-borough pockets, so the **Manhattan-tuned comp
   radius needs widening / per-type tuning** — the office/retail radius will under-fill for F.
2. **Land-value tail.** 96% are high-coverage (BldgArea/LotArea ≥ 0.3; 80% ≥ 0.8) where
   per-building-SF is a sound comp basis; but ~116 parcels (3.6%) are low-coverage
   (big-lot/small-building) where land drives value — warrants a **coverage-ratio disclosure**,
   not a rescope. SF distribution is unimodal, right-skewed, ~85% in 2,500–25,000 SF with a thin
   big-box tail handled by the existing size-dissimilar caution.

**Conclusion: industrial is buildable.** It cleared the same gate retail did; unlike commercial
condos, the comparability data exists (value on the parcel, ~100% SF, coordinates). Approved to
build as an engine extension per the locked build sequence (its own bucketing / SF-band / radius
caps, live via its own `_screen_view` interception branch, never by loosening the resolver gate).

## Industrial F-code comp configuration (LOCKED 2026-07-01)

The full industrial comp spec, locked for review before any build. **This is spec + config
only** — the engine, `_screen_view` interception, and any classifier logic are a LATER turn.
Config lives in `config/comp_criteria.json` → `industrial_config` (every number a tunable config
value, never hardcoded). Industrial is **NOT yet activated** (`F` is deliberately absent from
`activated_products`; it will go live via its own `_screen_view` interception branch, like
retail, never by loosening the resolver gate). Gate clearance recorded in the F-code Phase-2
entry above; all measurements below are **NYC Open Data direct** (roll `8y4t-faws` FY2027
`period='3'` final; PLUTO `64uk-42ks`), independent of the local DuckDB.

1. **Asset scope — `bldg_class` starts with `F` (all subcodes).** Present class-4 F-subcodes:
   F1 (factory/heavy), F2 + F4 (warehouse), F5 (light manufacturing), F8 (special / tank /
   utility-yard), F9 (misc). **ALL F-subcodes are IN SCOPE, including F8.** Self-storage **E7 is
   OUT** — it is an E-code, already excluded by the `startswith('F')` filter by construction (no
   extra logic needed).

2. **Value field — `curmkttot`** (DOF market value), same as office/retail. **Measured 99.9%
   populated** on F-codes (3,245 of 3,248 carry `curmkttot > 0` and `curtxbtot > 0`). Tax bill =
   `curtxbtot × class4_tax_rate` (FY2026 10.848%) — identical mechanics to the existing screens.

3. **SF source — PLUTO `BldgArea`**, measured **100% populated** on F-codes (3,248/3,248). Per-SF
   denominator fully supported.

4. **Comp radius — same auto-ladder as retail, higher ceiling.** Auto-radius 0.5 → 1.0 mi covers
   **~97% of F-codes** (clusters are dense-inside), so the ladder start/step are unchanged
   (`radius_start_miles` 0.5, `radius_step_miles` 0.1). Cap RAISED to **`radius_cap_miles` = 1.75
   mi** (tunable 1.5–2.0) to serve the sparse **~3% tail** (isolated parcels, Staten Island,
   Manhattan). **REFUSE beyond the cap** — never reach further. Not a wholesale wider radius; the
   same auto-radius as retail with a higher ceiling only.

5. **Subcode matching — same-subcode-first.** Prefer comps of the subject's own F-subcode
   (`subcode_match_first`). Fall back to **all-F pooling** (any F-subcode) ONLY when same-subcode
   cannot reach the minimum, and **DISCLOSE** the fallback: "extended to all industrial subcodes
   to reach comparable parcels."

6. **SF band — ±75% of subject `BldgArea`, proportional** (`sf_band` 0.75; not fixed buckets).
   Wider than office/retail's ±50% because industrial size is more dispersed; tunable, may adjust
   after validation. **Size-dissimilar comps flagged loudly** — the existing ✕ marker + per-SF
   handling ported from retail (in-band-only percentile, suppression-with-reason all carry over).

7. **Relaxation order (each step disclosed) — geography relaxes BEFORE subcode.**
   `same-subcode in-borough → same-subcode cross-borough → all-F cross-borough → refuse`. Reaching
   a different borough for a same-use peer is preferred over mixing use-types nearby: **use-type
   fidelity matters more than proximity** for industrial.

8. **Manhattan cascade (only ~30 F-codes citywide, a size grab-bag).** In-borough same-subcode
   ±75% first → if < 8, **reach the NEAREST outer-borough cluster first** → expand citywide only
   if the nearest cluster can't fill 8 → refuse if still < 8. **Every cross-borough reach
   disclosed.** (Manhattan industrial is too thin and too size-varied to self-fill.)

9. **Big-box tail (BldgArea ≥ 100,000 SF, ~67 parcels citywide).** Drop the SF-band ceiling
   entirely and take **nearest-by-size CITYWIDE with NO distance cap** (`big_box_sf_threshold`
   100000, `big_box_citywide_no_cap` — the retail K8 pattern). Fire a **mandatory "few true peers
   — directional, not precise" disclosure on every big-box screen**, disclose the max comp
   distance, and keep loud size-dissimilar flags. The 100K threshold is **measurement-backed**:
   peer counts collapse to 0–5 even at ±100% band / 3-mile reach above 100K SF. **Big-box is
   independent of the coverage disclosure** — NYC big-box is high-coverage (median 2.0, only 2 of
   67 below 0.30), so the coverage flag naturally never co-fires; they are independent conditions
   and need no special co-fire logic.

10. **Coverage / land-value disclosure — threshold 0.30, NYC-measured.** Fires when the SUBJECT
    **or 2+ comps** have `BldgArea / LotArea < 0.30` (land-dominant, so per-building-SF is
    skewed). **Disclosure only — non-computational**: it shows `BldgArea/LotArea` + `LotArea` for
    context and never filters, sorts, or refuses. The 0.30 threshold is set from the **measured
    full NYC F-code coverage distribution** (all 3,248 parcels): median coverage **1.00**, bulk
    p25–p75 = **0.89–1.31**, land-dominant tail begins ~0.35 and is unambiguous below 0.30;
    **0.30 fires on 116 parcels (3.6%)**. National industrial coverage ratios (0.10–0.35) are
    **meaningless for NYC**, where the median is 1.0 — this threshold is NYC-measured, not
    borrowed. Tunable (`coverage_ratio_threshold`). **F8** (special/tank-utility-yard, median
    coverage **0.08**) fires this on **~94% of F8 parcels — CORRECT and intended**: F8 is
    genuinely land-dominant (structure incidental to land). F8 stays in scope; near-universal
    firing on F8 is the designed behavior.

11. **Min comp count — 8, refuse below** (`min_comp_count` 8, same as office/retail).

**Population shape (context for the above, measured on all 3,248 F-codes):** skews to F5
light-manufacturing (1,365) + F4 warehouse (844) = 68%, then F9 (529), F1 (421), F2 (73), F8
(16); 84% Brooklyn + Queens (Bklyn 1,476, Qns 1,247), only ~30 Manhattan; SF distribution
unimodal, right-skewed, ~85% in 2,500–25,000 SF with a thin big-box tail. **Conclusion:
industrial is buildable on this configuration** — unlike commercial condos, the comparability
data exists (value on the parcel, ~100% SF, coordinates); the parameters above tune for
industrial's dispersion and land-value tail rather than working around missing data.

## Industrial land-dominant per-SF comp exclusion (LOCKED 2026-07-01)

The ONLY comp-quality fix from the industrial calibration session. CV/dispersion suppression
was measured and ABANDONED (continuum, no clean cutoff — mid p90 0.43 overlaps large p10 0.24;
not built). What WAS built:

- **Land-dominant comps are excluded from the per-SF calc only.** Any industrial comp with PLUTO
  coverage (BldgArea/LotArea) below `coverage_exclusion_threshold` (0.30) has a land-driven
  value, so its per-SF is not comparable — dropped from the per-SF mean/median/SD/percentile
  AND the per-SF chart. It STAYS in the value (curmkttot) distribution and the comp table,
  marked "land-dominant." Fires on ~24% of sets (measured). Disclosure: "N comp(s) excluded from
  per-SF as land-dominant (building covers under 30% of lot); still shown in the value
  distribution and comp table."
- **Two thresholds, one value now, tuned independently later.** `coverage_exclusion_threshold`
  (comp-side, per-SF exclusion) is a SEPARATE config key from `coverage_ratio_threshold`
  (subject-side disclosure). Both 0.30 deliberately.
- **Subject vs comp reconciliation (no contradiction).** Subject land-dominant = the subject's
  OWN per-SF is caveated (subject-side note). Comps land-dominant = EXCLUDED from per-SF
  (comp-side disclosure). The old comp-side wording ("N comps also land-dominant", which implied
  they were still in the stats) was removed.
- **Percentile filters STACK.** The per-SF percentile computes on comps that are (in-band, if
  band-relaxed) AND (not land-dominant); a comp in-band but land-dominant is out. `percentile_n`
  states the effective post-both-filter count; the sub-5 floor uses that post-filter count.
- **Floor guard (dead code at 0.30, insurance).** If the exclusion leaves < 5 usable per-SF
  comps, the per-SF stat is suppressed via the existing per-signal refusal path. Gated on an
  exclusion having occurred, so office/retail can never trip it.
- **Office/retail byte-identical.** The `land_dominant` flag is False on office/retail comps
  (never computed), so every shared-path branch (stats, serialize distributions/points/table,
  variance) is a no-op for them. Confirmed: office/retail PSF n, distribution, and comp table
  unchanged; excluded=0, no note, no marks.
