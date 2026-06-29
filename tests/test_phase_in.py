"""Phase-In Note + phase-in package (items 1-3). Every number is a subtraction of two
published roll values or a published prior-year value — no projection, no ÷5, no schedule.
"""
from screener.serialize import (
    _compact_dollars,
    _phase_in_bucket,
    _phase_in_note,
    _transitional_series_points,
)


class _Phase:
    def __init__(self, v, m=0.0, n=10):
        self.subject_value = v
        self.median = m
        self.n = n


def _subj(act=200_000_000, trn=190_000_000, py=185_000_000, roll_year="2027"):
    return {"curacttot": act, "curtrntot": trn, "pytrntot": py, "roll_year": roll_year}


# --- sign-aware meaning now lives ONLY on the labeled pending line (no duplicate) -----
def test_no_standalone_mechanism_field():
    # the older standalone sign-explanation sentence is removed; meaning is on the
    # labeled pending line instead.
    assert "mechanism" not in _phase_in_note(_Phase(-0.05), _subj())


def test_pending_fully_phased_state():
    # gap within threshold -> fully-phased wording, no caveat
    note = _phase_in_note(_Phase(0.0), _subj(act=200_000_000, trn=200_000_000))
    assert "fully phased in" in note["pending"]["label"]
    assert note["pending"]["caveat"] is None


def test_readable_formula_no_raw_columns():
    note = _phase_in_note(_Phase(0.05), _subj())
    assert "curacttot" not in note["formula"] and "curtrntot" not in note["formula"]


def test_fixed_descriptive_footer():
    assert _phase_in_note(_Phase(0.05), _subj())["footer"] == \
        "Descriptive only — not a verdict on the assessment."


# --- item 1/3: subject pending change = curacttot - curtrntot (labeled, sign-aware) ---
def test_pending_increase_positive_gap():
    # act 200M, trn 190M -> +10M pending increase (ramping up)
    note = _phase_in_note(_Phase(0.05), _subj(act=200_000_000, trn=190_000_000))
    assert note["pending"]["prefix"] == "Transitional Value vs. Assessed Value Gap"
    assert note["pending"]["display"] == "$10.0M"
    assert "increase still pending" in note["pending"]["label"]
    assert "not all at once" in note["pending"]["caveat"]


def test_pending_negative_when_ramping_down():
    # act 188.4M, trn 198.2M -> -9.8M (transitional exceeds actual; phasing down)
    note = _phase_in_note(_Phase(-0.05), _subj(act=188_421_300, trn=198_228_100))
    assert note["pending"]["display"] == "-$9.8M"
    assert "exceeds the actual assessed value" in note["pending"]["label"]


def test_pending_na_when_missing():
    note = _phase_in_note(_Phase(None), _subj(act=None, trn=None))
    assert note["pending"]["display"] == "n/a"
    assert note["pending"]["prefix"] == "Transitional Value vs. Assessed Value Gap"


# --- item 2/4: 5-year transitional-taxable series (gaps/exempt/tentative, consec %) -----
def _pt(year, value, period="3", exempt=False):
    return {"year": year, "value": value, "period": period, "exempt": exempt}


def _subj_series(points, roll_year="2027"):
    return {"curacttot": 200_000_000, "curtrntot": 190_000_000, "roll_year": roll_year,
            "taxable_series": points}


def test_full_five_year_series_with_consecutive_pct():
    pts = [_pt(2023, 100), _pt(2024, 110), _pt(2025, 99), _pt(2026, 99), _pt(2027, 120)]
    yrs = _phase_in_note(_Phase(0.0), _subj_series(pts))["realized_yoy"]["years"]
    assert [y["year"] for y in yrs] == [2023, 2024, 2025, 2026, 2027]
    assert all(y["status"] == "value" for y in yrs)
    assert yrs[0]["pct_from_prev"] is None                       # no year before the window start
    assert yrs[1]["pct_from_prev"] == "+10.00%"                  # 100 -> 110
    assert yrs[3]["pct_from_prev"] == "0.00%"                    # 99 -> 99 genuine zero, not blank


def test_missing_year_renders_as_gap_not_zero():
    pts = [_pt(2023, 100), _pt(2024, 110), _pt(2026, 130), _pt(2027, 140)]   # 2025 absent
    yrs = _phase_in_note(_Phase(0.0), _subj_series(pts))["realized_yoy"]["years"]
    g = next(y for y in yrs if y["year"] == 2025)
    assert g["status"] == "gap" and g["value"] is None and g["display"] == "—"
    # the gap breaks the consecutive chain: 2026 has no % (prior year 2025 missing)
    assert next(y for y in yrs if y["year"] == 2026)["pct_from_prev"] is None


def test_exempt_year_is_real_zero_distinct_from_gap():
    pts = [_pt(2023, 100), _pt(2024, 0, exempt=True), _pt(2025, 90), _pt(2026, 95), _pt(2027, 100)]
    yrs = _phase_in_note(_Phase(0.0), _subj_series(pts))["realized_yoy"]["years"]
    ex = next(y for y in yrs if y["year"] == 2024)
    assert ex["status"] == "exempt" and ex["display"] == "$0 (exempt)" and ex["value"] == 0.0


def test_newest_year_tentative_fallback_labeled():
    pts = [_pt(2023, 100), _pt(2024, 110), _pt(2025, 120), _pt(2026, 130),
           _pt(2027, 140, period="1")]                          # Final not out -> Tentative
    yrs = _phase_in_note(_Phase(0.0), _subj_series(pts))["realized_yoy"]["years"]
    newest = next(y for y in yrs if y["year"] == 2027)
    assert newest["status"] == "tentative" and "(tentative)" in newest["display"]


def test_series_falls_back_to_current_year_without_table():
    # no taxable_series attached -> single current-year point from curtxbtot, never crashes
    note = _phase_in_note(_Phase(0.0), {"curacttot": 2, "curtrntot": 1, "roll_year": "2027",
                                        "curtxbtot": 36_180_249})
    yrs = note["realized_yoy"]["years"]
    assert [y["year"] for y in yrs] == [2027] and yrs[0]["pct_from_prev"] is None


def test_series_unavailable_when_nothing_known():
    note = _phase_in_note(_Phase(0.0), {"curacttot": 2, "curtrntot": 1, "roll_year": None})
    assert note["realized_yoy"]["available"] is False


# --- item 3: comp Phase-In Gap bucket -------------------------------------------------
def test_phase_in_bucket_ramping_up():
    assert _phase_in_bucket(200_000_000, 188_000_000) == "$12.0M (Ramping Up)"


def test_phase_in_bucket_ramping_down():
    assert _phase_in_bucket(188_421_300, 198_228_100) == "-$9.8M (Ramping Down)"


def test_phase_in_bucket_fully_phased_within_threshold():
    # gap 0.1% of actual -> within 0.5% -> Fully Phased
    cell = _phase_in_bucket(200_000_000, 199_800_000)
    assert "(Fully Phased)" in cell


def test_phase_in_bucket_na_when_missing():
    assert _phase_in_bucket(None, 100) is None
    assert _phase_in_bucket(100, None) is None


def test_compact_dollars_formatting():
    assert _compact_dollars(13_221_672) == "$13.2M"
    assert _compact_dollars(-9_806_800) == "-$9.8M"
    assert _compact_dollars(450_000) == "$450k"
    assert _compact_dollars(None) == "n/a"


# --- no judgment language in any branch -----------------------------------------------
def test_no_judgment_words():
    for v, sub in [(0.05, _subj(200_000_000, 190_000_000)),
                   (-0.05, _subj(188_421_300, 198_228_100)),
                   (0.0, _subj(200_000_000, 200_000_000))]:
        note = _phase_in_note(_Phase(v), sub)
        blob = " ".join([note["pending"]["label"],
                         note["realized_yoy"].get("framing", ""),
                         note["pending"].get("caveat") or ""]).lower()
        for banned in ("over-taxation", "over-assessed", "too high", "too low", "drag", "should"):
            assert banned not in blob
