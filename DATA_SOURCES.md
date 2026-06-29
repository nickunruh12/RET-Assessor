# DATA_SOURCES.md

Dataset IDs, vintages, retrieval dates, access methods, source tier list. Update `retrieved` whenever you re-pull.

## Core — NYC v1

| Source | ID | What it gives | Access | Version / vintage | Retrieved |
|---|---|---|---|---|---|
| DOF Property Valuation & Assessment Data (Tax Classes 1–4) | `8y4t-faws` | Assessed/market values, tax class, building class, year built, dimensions, ZIP. **Multi-year — filter by `year`.** | SODA API + bulk CSV | FY2027 tentative roll is latest (`year='2027'`) | 2026-06-19 (live counts) |
| DCP PLUTO | `64uk-42ks` | `BldgArea` (gross-building-area source), `BldgClass`, `latitude`/`longitude` (distance-based comp ranking), **`NumFloors` (display-only Stories, 99.83% fill on office), `Address` (display-address fallback)**, `LotArea`, `YearBuilt` | Bulk CSV / SODA | **Release `26v1`** (version string from the data; SODA `rowsUpdatedAt` 2026-05-28). Data dictionary 26v1 (May 2026); readme 24v4 (Nov 2024) | **2026-06-21 (re-pulled with NumFloors + Address; 858,602 lots)** |
| DOF roll — 5-year transitional series | `8y4t-faws` | Subject `curtxbtot` per roll year 2023–2027 for the Phase-In Note series (`roll_taxable_series`). Same dataset as the main roll — a year-filter widening, NOT a new source. Each parcel-year has period 1 (Tentative, Jan) + period 3 (Final, May); the series uses **period 3 (Final)** via the SAME `FINAL_PERIOD_ORDER` dedup as `roll_class4`, partitioned per (BBL, year). Fetched column-projected (parid, year, period, curtxbtot, curmkttot, …) to avoid a multi-GB `*` re-pull; `roll_class4` (FY2027 canonical) is untouched and its count is unchanged. Subject-only; comp comparison stays single-year. | SODA API | window 2023–2027; `rowsUpdatedAt` 2026-06-15 | 2026-06-29 |
| DOF Property Abatement Detail | `rgyu-ii48` | **ICAP** abatement disclosure (subject banner + comp tag). Key `parid` is space-padded to 30 chars (trim → 10-digit BBL); `tccode` space-padded. Filter to current snapshot = `max(extractdt)`, `tccode='ICAP'`, reduce to DISTINCT BBL. Disclosure only — never changes the statutory tax. ICAP only for v1 (~89% of office abatement signal); other programs dropped. PILOT is NOT in this dataset. | SODA API | current snapshot `extractdt=2026-06-07` | 2026-06-29 |
| SODA API | — | `data.cityofnewyork.us/resource/{id}.json` with `$select`/`$where`/`$group` | HTTPS | n/a | n/a |
| DOF property lookup site | — | Ground-truth cross-check; the public record each citation links to. **Note: nyc.gov DOF domains are blocked from the agent browser — manual check.** | Web (not an API) | live | PENDING (manual) |
| PLUTO readme + data dictionary | — | Condo billing-lot aggregation + YearBuilt caveats. Treat as part of the codebase. | PDF | 26v1 / 24v4 | 2026-06-19 |
| DOF class 4 methodology + tax-rate pages | — | Value-field decision + mill rate. Primary source. | Web | FY2026 rate = 10.848% | 2026-06-19 (rate); methodology PENDING |
| NYC Tax Commission | — | Appeal process + deadline | Web | current | PENDING |

**SODA access note.** Get a free Socrata app token (`X-App-Token` header or `$$app_token=`) to avoid throttling on the multi-million-row roll.

**Vintage drift note.** The three data vintages refresh on **independent cadences** and are not bumped by a single action: the assessment roll (`8y4t-faws`) annually (by fiscal year), PLUTO (`64uk-42ks`) per release, and the ICAP abatement snapshot (`rgyu-ii48`) quarterly (re-run `python -m screener.abatements` to bump it). All three vintages are stamped in the provenance footer, so any drift between them is visible.

## Context and validation — NYC

- **ACRIS + DOF Rolling Sales** — sale prices. In v1 the purchase-vs-assessed gap runs on the price the *user* supplies; these are the validation/auto-fill source, not a hard dependency. Auto-pulling sale history is a later enhancement.
- **DOF condo/coop comparable rental PDFs** — the assessor's own comp logic; validation reference.
- **NYC Geoclient / DCP Geosupport** — address-to-BBL resolution. Free, needs an NYC API key.
- **Furman Center (NYU)** — evaluated, not used. Research republisher; license question + vintage lag when DOF + PLUTO give the same data direct and free. Recorded so the decision is not revisited.

## Later jurisdictions (each its own Phase 0–2 gate)

Chicago, Washington DC, San Francisco. Bookmark only.

## MCP reality check

No LLM in the v1 pipeline, so no MCP server is needed. Plain HTTPS to SODA is the entire integration. Revisit only if a cited-explanation layer is added later — and even then the MCP server would be your own, exposing your database to a model, not a third party's data to you.

## Banned sources (do not resurrect)

Trepp, Morningstar, Moody's CRE, CoStar, LoopNet, CompStak, CRED iQ, Yardi, RealPage, KBRA, Intex, Bloomberg, BOMA EER, IREM, NCREIF, RCA/MSCI, Cherre, RSMeans, Altus, CBRE/JLL/Cushman portals.

## Citation tuple (enforced in code from Phase 4)

Every derived row carries: `source_dataset`, `dataset_version`, `roll_year`, `retrieval_date`, `parcel_id` (for both sources). If a number cannot carry that tuple, it does not enter the database.
