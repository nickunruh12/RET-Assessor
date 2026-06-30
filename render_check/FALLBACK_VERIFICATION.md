# Retail broader-fallback — verification build record

Stage 2 (core-class retail comp pools), pre–Stage 3. Records the broader-retail fallback
disclosure verification, the SF-band message bug found and fixed, and the band-relax
size-dissimilarity behavior. Verified via the test route `/api/retail_screen` +
`/retail_screen` (retail is NOT public; K still refuses `out_of_scope_v1` on `/screen`).

Reference subject: **BBL 2054230001** (Bronx, building class K1, classified `retail_other`,
subject gross SF 7,306). Same-class comps were too thin locally, so the cascade reached the
broader-retail fallback. Commits: Stage 2 `e72ce00`; message fix `62450bc`.

---

## 1. Disclosure PASSED

**Cross-use note renders prominently.** When the fallback pulls other retail use-types, the
comp-set view renders, as its own block (`<p class="reconcile-note classification-note">`,
directly under the Subject Parcel panel):

> Fewer than 8 same-class comps nearby; comp set includes other retail use-types
> (specialized formats excluded).

The note fires only when cross-use comps are actually present (`fallback_triggered` and
`adjacent_count >= 1`); it is not shown when the set is all same-class.

**Cross-use comps are tagged per-row.** In the comp table, each comp's
"Exact Building-Class Match?" cell distinguishes same-mix from cross-use, reusing the office
exact/adjacent mechanism:

| match_type | row marker | meaning |
|---|---|---|
| `exact` | `✓` | same retail category as the subject (same-mix) |
| `adjacent` | `✗ (K4)` etc. | a different retail use-type pulled by the fallback (cross-use) |

For 2054230001 the rendered set was **7 same-mix (`✓`) + 1 cross-use (`✗ (K4)`)**, and the
comp-set composition line shows the count split (`7 exact / 1 adjacent`). Same-mix is always
included first; cross-use is only added to reach the 8-comp minimum (and is the only part
that is off-category), so the per-row tag and the composition count both make the blend
visible. No verdict language; banned-word grep clean.

---

## 2. SF-band message BUG — found and fixed (`62450bc`)

**Bug.** The comp-set summary line rendered
`(no gross-SF band: subject SF not reported)` whenever `sf_band_applied == False`. In the
retail fallback path that flag is false because the cascade **relaxed** the ±50% band to
reach the minimum — **not** because the subject's SF is missing. The subject's SF (7,306 for
2054230001) is present and displayed in the same view, so the message stated something false
and hid the real reason the set is size-heterogeneous.

**Fix.** Added `CompSet.sf_band_relaxed`, set True only when the cascade dropped the band
while the subject HAS SF (`bool(subj.sf) and not band_applied`). Office never sets it. The
message now branches on the real cause (three cases):

1. `sf_band_relaxed` → "gross-SF band relaxed to reach the 8-comp minimum; comp set includes
   size-dissimilar buildings"
2. else `not sf_band_applied` → "no gross-SF band: subject SF not reported" (office SF-null
   case, unchanged)
3. else → no message

**Verified:**
- 2054230001 (SF 7,306 present, fallback): `sf_band_relaxed=True` → renders the band-relaxed
  message, NOT "subject SF not reported".
- 3053480042 (office, SF genuinely null): `sf_band_relaxed=False`, `sf_band_applied=False` →
  still renders "no gross-SF band: subject SF not reported" (office unchanged).
- 1000630018 (retail_office, band held): neither message.

---

## 3. Band-relax size-dissimilarity behavior

When same-class SF-banded comps fall short, the cascade **relaxes the SF band before pulling
cross-use** (fixed order: band-relax → broader-retail fallback → refuse; distance is never a
relax lever and never exceeds the per-class cap). Crucially, size-dissimilar comps are
**kept to reach the 8-comp minimum and disclosed, never suppressed**:

- The band-relaxed comp set retains comps outside ±50% of the subject's BldgArea (that is how
  it reaches 8), rather than dropping them and refusing.
- The size-heterogeneity is disclosed via the band-relaxed message above
  ("…comp set includes size-dissimilar buildings"), so the reader is told the size control
  was loosened.
- The per-SF chart remains governed by the Stage-1 `per_sf_shown` flag independently; the
  value and tax-bill distributions render at full n regardless.

This is the intended trade (diagnosis: for these classes the SF band is the binding
constraint and local same-class buildings exist at other sizes; relaxing the band keeps comps
local and is the better trade than expanding distance). The behavior is surfaced, not hidden.

---

## 4. Per-SF size-outlier flagging (added on top of §3)

§3 disclosed-and-kept the band-relaxed set at the summary line. This layer makes the
size-dissimilar comps **impossible to miss INSIDE the per-SF view itself** — not just in the
summary line. It fires ONLY when the band was relaxed (`sf_band_relaxed`) AND the per-SF chart
is actually shown (`per_sf_shown`, i.e. pure retail — per-SF is NOT suppressed). Size-dissimilar
= comp BldgArea outside 0.5×–1.5× the subject's (reuses the comp-filter band; no new number).

Three surfaces, per-SF ONLY (value/tax charts untouched):
1. **Comp table** — each size-dissimilar row tagged `size-dissimilar` in the Comp SF cell.
2. **Per-SF chart** — size-dissimilar comps drawn as a distinct `×` marker in their own
   "size-dissimilar" series (separate from the gray in-band "comps" dots), so the outliers
   driving the per-SF spread are obvious on the chart.
3. **Per-SF header note** — "Comp set includes size-dissimilar buildings (band relaxed).
   Size-dissimilar comps flagged." (worded to avoid the banned word "outlier".)

**Verified — BBL 1000200012** (47 Broadway, **pure_retail**, per-SF SHOWN, band relaxed;
subject 27,640 SF, band 13,820–41,460): per-SF chart renders (not suppressed); 8 of 11 comps
are out-of-band and are flagged BOTH in the table (`class="size-flag"`, 18 row instances
across the views) AND on the chart (per-SF datasets = `comps:3, size-dissimilar:8, median,
mean, subject`); header note shows; value and tax charts carry zero size flags; no "outlier"
string anywhere in the HTML.

**Verified — clean set (band held)**: a pure-retail subject whose band held shows per-SF with
**zero** flags and no header note.

**NOTE on 2054230001** (this doc's reference subject): it is **`retail_other` (retail_share
0.78 < 0.80), so per-SF is SUPPRESSED** for the use-blend reason (unchanged). There is no
per-SF view for it, so the per-SF size-outlier flagging does **not** apply — confirmed: per-SF
refused, `per_sf_size_flag` absent, no size flags. The per-SF flagging is demonstrated on
1000200012 (pure retail, per-SF shown, band relaxed) instead. Mixed-class per-SF suppression
was left untouched.

---

_Reproduce: `python -m screener.retail_loader --skip-fetch` then screen the BBLs above via
`/api/retail_screen?bbl=...`. Tests: `tests/test_retail_comps.py` (261 passing; render_check
banned-word grep clean)._
