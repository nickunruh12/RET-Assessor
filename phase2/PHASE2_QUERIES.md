# Phase 2 — exact SODA queries (copy-paste)

These are the kill-gate queries. The build sandbox cannot reach `data.cityofnewyork.us`,
so run `run_phase2.py` locally, or paste these URLs into a browser / `curl`. Append a free
app token to dodge throttling: add `&$$app_token=YOUR_TOKEN`.

**Column names below are the likely ones; `run_phase2.py` introspects and confirms them.**
Confirm `taxclass`, `yearbuilt`, `bldgcl`, `zip` against the row the introspection step prints.

## Step 0 — introspect columns (resolve the value-field minefield)

```
https://data.cityofnewyork.us/resource/8y4t-faws.json?$limit=1
```
Read every column. Identify the single value field for comparison (look for `fullval` /
market-value columns vs `avtot`/`avland` actual-assessed vs transitional). Lock one in DECISIONS.md.

## Step 1 — ROLL fill rates (class 4)

Total class 4 parcels:
```
https://data.cityofnewyork.us/resource/8y4t-faws.json?$select=count(*)&$where=taxclass='4'
```
Non-null year built:
```
https://data.cityofnewyork.us/resource/8y4t-faws.json?$select=count(*)&$where=taxclass='4' AND yearbuilt IS NOT NULL AND yearbuilt!='0'
```
Non-null building class:
```
https://data.cityofnewyork.us/resource/8y4t-faws.json?$select=count(*)&$where=taxclass='4' AND bldgcl IS NOT NULL AND bldgcl!=''
```
Non-null ZIP:
```
https://data.cityofnewyork.us/resource/8y4t-faws.json?$select=count(*)&$where=taxclass='4' AND zip IS NOT NULL
```
Fill rate = non-null ÷ total. **Gate: ≥80%.**

## Step 1b — PLUTO BldgArea fill (commercial classes)

Total commercial PLUTO lots:
```
https://data.cityofnewyork.us/resource/64uk-42ks.json?$select=count(*)&$where=starts_with(bldgclass,'O') OR starts_with(bldgclass,'K')
```
Non-null BldgArea among them:
```
https://data.cityofnewyork.us/resource/64uk-42ks.json?$select=count(*)&$where=(starts_with(bldgclass,'O') OR starts_with(bldgclass,'K')) AND bldgarea IS NOT NULL AND bldgarea!='0'
```

## Step 3 — ground-truth sample

```
https://data.cityofnewyork.us/resource/8y4t-faws.json?$where=taxclass='4'&$limit=20&$select=bble,taxclass,bldgcl,zip,fullval
```
Look each BBL up on the public DOF property lookup; confirm API values match. Disclose any vintage lag.

## Gate decisions to record after running

| Gate | Threshold | If it fails |
|---|---|---|
| Year built fill | ~80% on class 4 | Demote vintage to display-only (not a comp criterion) |
| PLUTO BldgArea fill | ~80% on commercial | Re-scope comp definition before continuing |
| Value-field ambiguity | one field, consistent | Cannot state it → resolve against DOF before Phase 4 |
| API vs DOF lookup | match | Lag undisclosed → fix disclosure |
