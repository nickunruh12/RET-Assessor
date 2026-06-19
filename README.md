# NYC Commercial Assessment Outlier Screener

Solo build. NYU Schack portfolio piece. NYC tax class 4 (commercial) only, v1.

## The one rule

Every number on screen traces to either a published public field or a value the user typed in. Nothing in between is invented. If the tool cannot cite it or the user did not supply it, the tool does not say it. No tool-asserted market cap rate, no true-value verdict, no "you should appeal."

## Three layers, kept strictly separate in code

- **SIGNAL** — public, deterministic, no LLM. Assessed-value distribution + percentile, tax-bill distribution + percentile, assessment-ratio deviation vs 45% target, purchase-price-vs-DOF-market-value gap (when supplied), YoY assessment-change vs comp set (when two roll years loaded).
- **CONTEXT** — display only, cited, never part of any calculation. Mill rate, reassessment cycle, RET/transfer tax law, appeal process and deadline.
- **RUNG 3** — opt-in, off by default, visually partitioned. User enters own NOI; tool returns assessor's implied cap rate = DOF market value ÷ user NOI. Displayed only, no comparison rate, no verdict.

## Repo map

- `DECISIONS.md` — every irreversible choice, dated, with reason
- `DATA_SOURCES.md` — dataset IDs, vintages, retrieval dates, source tier list
- `KNOWN_LIMITS.md` — what the tool refuses to do and why
- `PHASE0_DIFFERENTIATION.md` — competitor recheck + how this differs
- `sources/nyc_sources.json` — machine-readable per-jurisdiction source document
- `sources/nyc_sources_companion.md` — human-readable companion
- `docs/INPUT_SPEC.md` — Phase 3 tiered input design
- `phase2/run_phase2.py` — self-introspecting fill-rate + ground-truth gate script
- `phase2/PHASE2_QUERIES.md` — the exact SODA queries, copy-pasteable

## Status (2026-06-19)

Phases 0, 1, 3 deliverables drafted and fact-checked against primary-source citations.
**Phase 2 (fill-rate kill gates) is the open blocker** — requires live SODA queries against
NYC Open Data, which the build environment cannot reach. Run `phase2/run_phase2.py` from a
machine with internet access, or paste the queries from `phase2/PHASE2_QUERIES.md` into a browser.
The kill-or-proceed call is made on those numbers before any engine code is written.
