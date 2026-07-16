# Land-valuation contract — DRAFT v1 (blocked on a data kill-gate, not implemented)

`contract_version: 1.0.0` · `product: "land"` · auto-routed via `/api/screen` (no new user route)

Class-V (vacant land) parcels are **auto-detected and routed** to a land-valuation screen — the
same interception pattern retail (K) and industrial (F) use. The user does not choose "land mode";
the tool detects a vacant parcel and switches the comp basis from building-SF to **buildable-SF**
(lot area × zoning FAR), because vacant land has no building to normalize against.

> **Status: BLOCKED.** The current DB does **not** carry the zoning/FAR data this needs. Before any
> of this is built, a **data kill-gate** (below) must measure whether that data is available and
> dense enough. If it fails, this contract is shelved. This doc fixes the target shape so the
> gate has something concrete to validate against.

## Detection / routing (not a user choice)

- Trigger: subject `bldg_class` starts with `"V"` (vacant land; class-4). There are **8,118** such
  parcels in the loaded class-4 roll today — they currently refuse as `out_of_scope_v1`.
- Routing: `_screen_view` intercepts `bldg_class.startswith("V")` → `build_land_screen_view(...)`,
  exactly as it does for `"K"`/`"F"`. The broad out-of-scope gate stays untouched; office/retail/
  industrial paths are unchanged.
- Request is the **same** as `/api/screen` (`bbl` or resolved address). No new request fields; the
  product is inferred from the parcel, never passed in. (This mirrors the hard architectural rule:
  asset type is measured from the parcel, never a dropdown.)

## Response (success) — `status: "ok"`

Same envelope as `/api/screen`, with a **land-specific signal set** and a **land block**:

```jsonc
{
  "status": "ok",
  "product": "land",
  "contract_version": "1.0.0",
  "disclaimer": "…",
  "subject": {                          // subject panel + land-specific fields
    "bbl": "…", "bldg_class": "V1", "borough": "…", "zip_code": "…",
    "lot_area_sf": 10000,               // PLUTO LotArea (present today)
    "zoning_district": "M1-5",          // NEW DATA (PLUTO zonedist1) — NOT in DB today
    "far_basis": "commercial",          // which FAR governs (resid/comm/facil), from class/zoning
    "far": 5.0,                         // NEW DATA (PLUTO commfar/residfar/facilfar) — NOT in DB today
    "buildable_sf_estimate": 50000,     // DERIVED = lot_area_sf × far (as-of-right estimate)
    "assessed_market_value": 4200000    // curmkttot (roll)
  },

  "land": {                             // NEW product block
    "comp_basis": "value_per_buildable_sf",   // primary land metric
    "zoning_match": {                    // how comps were matched
      "subject_district": "M1-5",
      "match_rule": "same_zoning_district_then_compatible_far_band",
      "matched_on": "same_district",     // "same_district" | "compatible_far" | "relaxed"
      "far_band_pct": 0.25               // when matched on FAR band, ±this fraction of subject FAR
    },
    "radius_used_miles": 0.75,
    "comp_count": 9
  },

  "signals": [                          // land signals (NOT the building signals)
    {
      "key": "mv_per_buildable_sf",     // PRIMARY: curmkttot / buildable_sf_estimate
      "label": "DOF Market Value per Buildable SF (est., lot × FAR)",
      "unit": "$/buildable_sf",
      "n": 9, "mean": …, "median": …, "minimum": …, "maximum": …, "stddev": …,
      "subject_value": …, "subject_percentile": …,
      "dispersion": { "sd_band": "…", "iqr": "…", "cv": "…" },
      "distribution": [ … ], "comp_points": [ … ],
      "refused": false, "percentile_note": null
    },
    {
      "key": "mv_per_lot_sf",           // SECONDARY: curmkttot / lot_area_sf (no zoning assumption)
      "label": "DOF Market Value per Lot SF",
      "unit": "$/lot_sf",
      "…": "same shape"
    },
    { "key": "assessed_value_market", "…": "total EMV distribution — same as other products" }
  ],

  "comps": [ … ],                       // comp rows: bbl, address, lot_sf, zoning_district, far,
                                        // buildable_sf, distance, $/buildable-sf vs subject, cited
  "disclosures": {                      // land-specific disclosure strings (see below)
    "buildable_sf_basis": "…",
    "zoning_match_basis": "…",
    "estimate_caveat": "…"
  },
  "provenance": { … },
  "context": { … }
}
```

### Land signals rationale
- **`mv_per_buildable_sf`** is the primary basis — vacant land trades on developable area, and
  buildable SF (lot × FAR) is the standard normalizer. It depends entirely on the NEW zoning/FAR
  data.
- **`mv_per_lot_sf`** is a fallback that needs **no** zoning data (lot area is already loaded). If
  the kill-gate shows FAR coverage is too thin, a lot-SF-only screen may be the shippable subset —
  document that as the degraded mode, not silent omission.

## New DATA the current DB lacks (and the kill-gate)

The loaded `parcels` table has `pluto_lotarea` but **no zoning district and no FAR** — confirmed:
the only zoning/lot column present is `pluto_lotarea`. To compute `buildable_sf` and match comps by
zoning, the loader must add, from PLUTO (`64uk-42ks`, same release already used):

| New field | PLUTO source | Used for |
|---|---|---|
| `zoning_district` | `zonedist1` | comp matching (same-district first) |
| `resid_far` / `comm_far` / `facil_far` | `residfar` / `commfar` / `facilfar` | the governing FAR → buildable SF |
| (derived) `buildable_sf` | `lotarea × governing FAR` | the primary land metric |
| (optional) `built_far` | `builtfar` | sanity/vacancy check (near 0 confirms undeveloped) |

### DATA KILL-GATE (must pass before any build)

Mirrors the office/industrial kill-gate pattern — a read-only measurement over the ~8,118 class-4
V parcels, with go/no-go thresholds fixed **before** measuring:

1. **Zoning-district fill**: `zonedist1` present for **≥ 90%** of class-4 V parcels.
2. **Governing-FAR fill**: a usable, non-zero governing FAR present for **≥ 80%**. (Many lots have
   FAR = 0 or split districts; those can't yield a buildable-SF estimate.)
3. **Comp-pool viability**: for **≥ 60%** of V subjects, **≥ 8** same-district (or compatible-FAR)
   V comps exist within the radius cap. Below this, the primary buildable-SF screen can't field a
   distribution for most subjects.
4. **Buildable-SF sanity**: derived `buildable_sf` is positive and finite for the same population
   used in (3); spot-check a sample against known parcels.

**Outcomes:**
- All pass → build the full `mv_per_buildable_sf` screen.
- (1)+(3) pass but (2) fails → ship the **degraded** `mv_per_lot_sf`-only screen (no FAR), clearly
  labeled, and shelve buildable-SF.
- (3) fails broadly → shelve land valuation; V parcels keep refusing (honest `out_of_scope`), no
  half-built screen.

The gate result and thresholds get logged to `DECISIONS.md` like every other kill-gate.

## Disclosure fields (every one required when the buildable-SF basis is shown)

- **`buildable_sf_basis`**: "Buildable SF is an as-of-right estimate = lot area × PLUTO zoning FAR
  (`residfar`/`commfar`/`facilfar`). It excludes bonuses, inclusionary/air-rights transfers, special
  district overrides, and assemblage — actual developable area may differ."
- **`zoning_match_basis`**: states how comps were matched (same district vs compatible FAR band vs
  relaxed), and that a zoning match is not an appraisal of highest-and-best use.
- **`estimate_caveat`**: "$/buildable-SF is a screening distribution against public data, not an
  appraisal or a development pro forma. No verdict on value is implied." (no-verdict discipline)
- **`far_split_note`** (conditional): when `zonedist1` is a split/overlay or FAR is ambiguous, say
  so and fall back to `mv_per_lot_sf` for that subject.
- **`land_data_provenance`**: cites the PLUTO release the zoning/FAR came from (dataset + version),
  same provenance discipline as every other figure.

## Reuse vs new

**Reuses:** the `/api/screen` envelope, `CompSet`/`CompRow`, `compute_stats` (distributions /
percentiles / dispersion are metric-agnostic), `compute_variance`, `build_screen_view` assembly,
citations/provenance, and the K/F-style interception mechanism in `_screen_view`.

**New (must build, and only after the kill-gate passes):**
- Loader change: pull `zonedist1` + `residfar`/`commfar`/`facilfar` (+ optional `builtfar`) into
  `parcels`; derive `buildable_sf`. (This is the data work the gate authorizes.)
- `build_land_screen_view` + a `select_land_comps` that matches on zoning district / FAR band within
  a radius (new selection basis; not size-band).
- The two land signals (`mv_per_buildable_sf`, `mv_per_lot_sf`) and the `land` + `disclosures` blocks.
- `_screen_view` interception for `bldg_class.startswith("V")`.

**Hard rule:** buildable SF and any FAR-derived number must always ship with the
`buildable_sf_basis` disclosure — an estimate is never presented as a measured fact.
