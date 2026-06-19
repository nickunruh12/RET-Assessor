# Phase 2 — results (live SODA queries, run 2026-06-19)

Run against `8y4t-faws` and `64uk-42ks` via browser. Dataset is the FY2027 tentative roll (latest `year`).

## Structural findings (these change the build, not just the gates)

1. **`8y4t-faws` is the full multi-year historical roll, not a single roll.** Class-4 rows across all years = 1,303,243. A single roll year (`year='2027'`) = **263,023** class-4 records. **The loader MUST filter by `year`.** Upside: the YoY assessment-spike SIGNAL needs no separate dataset — two roll years live in one source.
2. **Real column names** (the roadmap's guesses were wrong): tax class = `curtaxclass` (not `taxclass`); year built = `yrbuilt`; building class = `bldg_class`; ZIP = `zip_code`; BBL = `parid`.
3. **The roll already carries a SF field, `gross_sqft`,** plus use-type breakdowns (`office_area_gross`, `retail_area_gross`, etc.). The roadmap assumed the roll had no SF field. Fill is only ~72% on class 4, so PLUTO is still the better SF source — but `gross_sqft` is a viable fallback that avoids the join for many parcels.
4. **Value fields are snapshot-prefixed:** `py`/`ten`/`cbn`/`fin`/`cur` × `mktland/mkttot/actland/acttot/trnland/trntot/txbtot`. `finmkttot` (final market value) is **0 on the FY2027 tentative roll** because the final roll isn't published yet. Use `curmkttot` (current) now; switch to `finmkttot` when the final roll posts.
5. **`curacttot` = exactly 0.45 × `curmkttot` on every class-4 row sampled.** The actual assessed value is a mechanical 45% of market value. See the design implication below.

## Fill-rate gates — FY2027 roll, class 4 (n = 263,023)

| Field | Non-null | Rate | Gate (≥80%) | Action |
|---|---|---|---|---|
| Building class (`bldg_class`) | 263,023 | **100.0%** | PASS | Strong comp criterion |
| ZIP (`zip_code`) | 261,813 | **99.5%** | PASS | Strong location criterion |
| Year built (`yrbuilt`) | 179,031 | **68.1%** | **FAIL** | Demote vintage to display-only |
| SF — roll `gross_sqft` | 188,932 | **71.8%** | marginal | Fallback only |
| SF — PLUTO `BldgArea`, commercial (O*/K*) | 25,922 / 25,927 | **99.98%** | PASS | **Primary SF source** |

## Value-field lock (resolves the Phase 2 Step 2 minefield)

- **Distribution / market value comparison:** `curmkttot` (current market value total). Switch to `finmkttot` once the final roll publishes.
- **Tax-bill SIGNAL:** taxable value (`curtxbtot`, the post-phase-in transitional taxable) × FY2026 class-4 rate 10.848%.
- **Never mix** `cur`/`fin`/`ten` snapshots across comps, and never mix `mkttot` (market) with `acttot` (assessed) or `trntot` (transitional).

## DESIGN IMPLICATION — the assessment-ratio SIGNAL is near-useless for class 4

The roadmap's SIGNAL "flag the subject's assessment ratio (actual assessed ÷ DOF market value) against the 45% target." But `curacttot` is *defined* as 0.45 × `curmkttot`, so this ratio is ~45% for every parcel by construction. It carries no information and would flag nothing. The discriminating variation lives elsewhere:
- **Market value per SF** (`curmkttot ÷ BldgArea`) across the comp set — this is where an outlier assessment actually shows up.
- **Transitional vs actual gap** (`curtrntot` vs `curacttot`) — shows how much of an increase is still being phased in.

Recommend dropping the ratio-vs-45% SIGNAL and replacing it with a **market-value-per-SF percentile**. This is a design decision for you (see below).

## Ground-truth cross-check — DONE (PASSED 5/5)

Manually verified 5 class-4 parcels against the official DOF property lookup (a836-pts-access.nyc.gov), 2026-06-19. API `curmkttot` matched DOF published market value **exactly, to the dollar, on all 5.**

| Address | BBL (parid) | API `curmkttot` | DOF market value | Result |
|---|---|---|---|---|
| 438 Greenwich St | 1002230035 | 1,700,000 | 1,700,000 | MATCH |
| 646 East 12 St | 1003940032 | 2,578,000 | 2,578,000 | MATCH |
| 356 West 12 St | 1006400041 | 4,820,000 | 4,820,000 | MATCH |
| 4 Doyers St | 1001620044 | 1,740,000 | 1,740,000 | MATCH |
| 171 Christopher St | 1006360033 | 1,158,000 | 1,158,000 | MATCH |

**No vintage lag.** DOF labels these "2026-2027 Final" and `curmkttot` matches the final figure exactly — the API is current with the FY2027 final roll, not a roll behind. The earlier "API may lag DOF" assumption was wrong and is superseded.

**Tax-bill basis confirmed = transitional taxable.** DOF shows three distinct values per parcel: ESTIMATED MARKET VALUE (=`curmkttot`), MARKET AV (=`curacttot`, the mechanical 45%), and TRANS AV labeled "Your 2026/27 Taxes Will Be Based On" (=`curtxbtot`). Taxes are levied on the transitional taxable, lower than actual assessed during phase-in (e.g. 438 Greenwich: actual 765,000 vs transitional 709,500). The tax-bill SIGNAL computes `curtxbtot` × 10.848%, never `curacttot`.

## Sample (FY2027, class 4, O1 offices — the 5 verified rows are the first three + rows 4–5)

| BBL (parid) | Class | ZIP | curmkttot | curacttot | ratio | gross_sqft | yrbuilt |
|---|---|---|---|---|---|---|---|
| 1002230035 | O1 | 10013 | 1,700,000 | 765,000 | 0.45 | 3,250 | 1920 |
| 1003940032 | O1 | 10009 | 2,578,000 | 1,160,100 | 0.45 | 5,165 | 1951 |
| 1006400041 | O1 | 10014 | 4,820,000 | 2,169,000 | 0.45 | 7,370 | 1920 |
| 1001620044 | O1 | 10013 | 1,740,000 | 783,000 | 0.45 | 3,298 | 1977 |
| 1006360033 | O1 | 10014 | 1,158,000 | 521,100 | 0.45 | 2,046 | 1946 |

(7 more in the run log.)
