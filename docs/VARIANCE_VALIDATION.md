# Variance-layer validation (run 2026-06-21)

`PYTHONPATH=src python scripts/validate_variance.py`. Descriptive attribute-diff only —
no statistics changes, no causal language, no rendering. Three single-dimension views
per subject; the full attribute-diff set stays queryable underneath.

## Subjects

### In-line — `1000100016` (O4 Manhattan, 336,025 SF, $68.07M), 28 comps
Nearest-by-distance and nearest-by-SF comps cluster around the subject (e.g. nearest-SF
`1000210004`: SF −0%, assessed −20%; `1000110021`: SF +8%, assessed +8%). The subject's
assessment sits within range of the comps most like it.

### Out-of-range / outlier — `1000090014` (O4 Manhattan, 544,015 SF, $162.12M), 28 comps
The strong signal fires: the nearest-by-distance and nearest-by-SF comps are almost all
assessed **lower** — nearest-SF `1000330001` (SF −0%) is **−9%**, and nearby comps run
**−33% to −65%**; most-different reaches **−77%**. The subject is out of range of its
closest peers. The views show the picture; **no verdict is rendered.**

### Missing-vintage — `3001720050` (O2 Brooklyn, 18,276 SF), 8 comps
Two comps carry **"year built n/a"** (`3004120038`, `3004120033`); the rest show
`year built YYYY vs 1925`. Vintage is displayed when present, flagged when missing, and
**never** orders any view.

## Confirmations
- **No causal language** — banned-word scan over **123 output lines returned CLEAN**
  (`because`, `due to`, `driven by`, `explained by`, `caused by`, `reason`, … — none present).
  Every `differs_on` string is pure side-by-side: "Comp assessed X% higher/lower than
  subject; match exact; class O4 vs O4; SF … vs …; distance … mi; year built … vs …".
- **Three single-dimension views**, each labeled with the one dimension it orders by
  (`distance_miles`, `abs(sf_pct_diff)`, `abs(assessed_pct_diff)`) — no blended similarity score.
- **Vintage never sorts** — view dimensions contain no year/vintage term; it is display-only.
- **Provenance on every row** — citation tuple (`source_dataset@roll_year`, retrieval date)
  + the PLUTO version for the SF attribute.
- **Full set queryable** — `all_diffs` holds every comp (e.g. filter `assessed_pct_diff > 25%`
  returned 3 rows for the in-line subject); the views are just ordered windows over it.

## Rule restated
The table shows how each comp DIFFERS from the subject on published attributes and never
states or implies WHY. The nearest-by-distance / nearest-by-SF views are the legitimate
red flag when a subject is out of range of its closest peers; the most-different view is
context for spread. The human infers cause; the tool renders no verdict.
