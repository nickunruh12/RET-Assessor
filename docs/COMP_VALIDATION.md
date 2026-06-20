# Comp-selector validation — office / distance / radius-first (run 2026-06-19)

Full census: `select_comps` run over **all 7,160 office subjects** (office, SF-eligible,
non-condo, has PLUTO coords). Reproduce with `PYTHONPATH=src python scripts/validate_comps.py`.
Criteria as locked: office buckets (O1–O4 exact, O5+O6, O7+O8+O9), gross-SF ±50%,
distance from PLUTO lat/lon, radius 0.5→1.0 mi, min 8.

## (d) Parcel count per office class / bucket — bucketing holds

| Class | n | Bucket |
|---|---|---|
| O1 | 449 | O1 (exact) |
| O2 | 1,375 | O2 (exact) |
| O3 | 119 | O3 (exact) |
| O4 | 400 | O4 (exact) |
| O5 | 1,817 | O5_O6 |
| O6 | 950 | O5_O6 (2,767) |
| O7 | 1,189 | O7_O9 |
| O8 | 679 | O7_O9 |
| O9 | 182 | O7_O9 (2,050) |

Total office universe = **7,160**. Class→bucket mapping is exactly as configured.

## (c) Refusal rate — 36.5% overall (all refusals = insufficient comps within 1 mi)

| Borough | Subjects | Refused |
|---|---|---|
| Manhattan | 2,478 | **10.5%** |
| Staten Island | 702 | 45.0% |
| Brooklyn | 1,779 | 37.9% |
| Queens | 1,611 | 60.3% |
| Bronx | 590 | 66.8% |

| Bucket | Subjects | Refused |
|---|---|---|
| O1 | 449 | **94.2%** |
| O3 | 119 | 78.2% |
| O2 | 1,375 | 52.7% |
| O7_O9 | 2,050 | 33.4% |
| O5_O6 | 2,767 | 24.4% |
| O4 | 400 | **4.5%** |

## (b) Radius-used distribution

- Succeeded at 0.5 mi (no expansion): **2,722 (38.0%)**
- Succeeded only after expansion (0.6–1.0 mi): **1,822 (25.4%)**
- Refused at 1.0 mi cap: **2,616 (36.5%)**

Expansion histogram (successes): 0.5→2,722 · 0.6→389 · 0.7→340 · 0.8→413 · 0.9→355 · 1.0→325.

## (a) Comp-set size distribution (4,544 successful subjects)

min 8 · p10 8 · p25 9 · **median 11** · p75 46 · p90 100 · max 214.
Bands: 8–14 → 2,669 · 15–29 → 463 · 30–59 → 452 · 60–119 → 677 · 120+ → 283.
Bimodal: outer-borough successes barely clear the floor of 8; dense Manhattan office runs 100+.

## Reading

- **Bucketing is structurally correct** and the min-8 floor is respected (no success below 8).
- **The exact O1/O2/O3 buckets starve.** O1 refuses 94%, O3 78%, O2 53% — these are sparse,
  geographically dispersed classes, and exact bucketing + ±50% SF + 1-mi cap leaves most
  subjects short. O4 (clustered downtown) and the grouped buckets fare far better.
- **Refusal is overwhelmingly an outer-borough phenomenon** (Bronx/Queens 60–67% vs Manhattan 10%).
- All knobs (bucket map, SF band, radii, min count) are config-tunable — open question below.

## Open question for review (not changed without a decision)

The locked exact-bucketing for O1/O2/O3 produces high refusal rates. Options if undesirable:
loosen those buckets (e.g. group O1+O2+O3 like the rare codes), widen the radius cap, or accept
the refusals as honest "insufficient comparable properties." No change made — flagged for Phase 6.
