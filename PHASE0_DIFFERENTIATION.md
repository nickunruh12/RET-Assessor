# Phase 0 — Dead-tool recheck and differentiation

**Date:** 2026-06-19. **Method:** Web search (NYC Open Data, NYC Tax Commission, TaxProper, Ownwell, SeeThroughNY, general "NYC commercial assessment comparison").

## What exists

| Tool | What it is | Free? | Commercial? | Parcel-level comp distribution? | Provenance / citations? | Verdict-free? |
|---|---|---|---|---|---|---|
| **Ownwell** | Full-service appeal filer; takes ~25% of savings | No (contingency fee) | Yes (incl. asset managers) | No — internal, opaque | No | No — its product *is* the verdict |
| **TaxProper** | Same model, primary markets TX/CA | No | Unconfirmed for NYC | No | No | No |
| **TaxNetUSA QuickAppeal** | Comp/appeal tool for consultants (your noted nearest commercial comp) | No (paid) | Yes | Partial — consultant-facing | Limited | No — verdict-oriented |
| **SeeThroughNY property tax calculator** | Compares tax *bills across localities* | Yes | No — residential/locality framing | No | Partial | N/A |
| **SmartAsset / NYPropertyCheck** | Rate estimators / record lookup | Yes | No | No | No | N/A |
| **NYC DOF property lookup** | Official per-parcel record | Yes | Yes | No — single parcel, no peer set | Yes (it is the source) | N/A |
| **NYC Open Data 8y4t-faws + PLUTO** | Raw datasets | Yes | Yes | No — raw, you build the comps yourself | Yes | N/A |

Residential appeal services are crowded. No free, self-serve, **provenance-first commercial assessment-comp screener with explicit refusal logic** surfaced.

## How this tool differs (the paragraph for the repo)

The closest commercial products — Ownwell and TaxProper (contingency-fee appeal filers) and TaxNetUSA QuickAppeal (a paid, Texas-only, consultant-facing appeal tool) — all output a verdict ("we think you're over-assessed, let us file") on comp logic the user never sees. This tool inverts that, and it is built for a different user: the **CRE underwriter sanity-checking a tax basis**, not a property owner shopping an appeal. It never renders a verdict, it shows exactly where a parcel's assessed value sits in a distribution of comparable class 4 parcels, and every figure carries its source dataset, roll year, version, retrieval date, and a link to the public record. It refuses out loud when the comparable set is too thin rather than reaching for dissimilar comps to manufacture a number. The free public tools either operate one parcel at a time (DOF lookup), compare jurisdictions rather than parcels (SeeThroughNY), or hand you raw rows you must assemble yourself (Open Data). The differentiator is the combination — peer-set distributions, hard provenance, and visible refusal — built on free public data with no verdict layer.

## Gate result

**PASS.** No identical free commercial screener found. Difference is articulable. Proceed.

## Manual checks — DONE

- **AI.Edge / ACRE forum recheck — CLEARED 2026-06-19.** Nick confirmed no competing tool. Standing rule satisfied for Phase 4.

## Sources

- [NYC Open Data 8y4t-faws — Property Valuation and Assessment Data](https://data.cityofnewyork.us/City-Government/Property-Valuation-and-Assessment-Data-Tax-Classes/8y4t-faws)
- [Ownwell — Property Tax Appeal](https://www.ownwell.com/appeals)
- [TaxFightBack — Best Property Tax Appeal Companies in New York (2026)](https://taxfightback.com/articles/competitor-comparisons/best-property-tax-appeal-companies-new-york)
- [SeeThroughNY — Property Tax Calculator](https://www.seethroughny.net/benchmarking/property-tax-calculator)
