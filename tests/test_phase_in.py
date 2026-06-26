"""Phase-In Note + phase-in package (items 1-3). Every number is a subtraction of two
published roll values or a published prior-year value — no projection, no ÷5, no schedule.
"""
from screener.serialize import _compact_dollars, _phase_in_bucket, _phase_in_note


class _Phase:
    def __init__(self, v, m=0.0, n=10):
        self.subject_value = v
        self.median = m
        self.n = n


def _subj(act=200_000_000, trn=190_000_000, py=185_000_000):
    return {"curacttot": act, "curtrntot": trn, "pytrntot": py}


# --- mechanism branches (existing behaviour) ------------------------------------------
def test_positive_gap_branch():
    note = _phase_in_note(_Phase(0.05), _subj())
    assert "positive gap" in note["mechanism"] and "ramping up" in note["mechanism"]


def test_negative_gap_branch():
    note = _phase_in_note(_Phase(-0.05), _subj())
    assert "negative gap" in note["mechanism"] and "ramping down" in note["mechanism"]


def test_near_zero_branch():
    note = _phase_in_note(_Phase(0.0), _subj())
    assert "fully phased in" in note["mechanism"]


def test_readable_formula_no_raw_columns():
    note = _phase_in_note(_Phase(0.05), _subj())
    assert "curacttot" not in note["formula"] and "curtrntot" not in note["formula"]


def test_fixed_descriptive_footer():
    assert _phase_in_note(_Phase(0.05), _subj())["footer"] == \
        "Descriptive only — not a verdict on the assessment."


# --- item 1: subject pending change = curacttot - curtrntot (sign-aware) --------------
def test_pending_increase_positive_gap():
    # act 200M, trn 190M -> +10M pending increase (ramping up)
    note = _phase_in_note(_Phase(0.05), _subj(act=200_000_000, trn=190_000_000))
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


# --- item 2: realized YoY = curtrntot - pytrntot --------------------------------------
def test_realized_yoy_available():
    note = _phase_in_note(_Phase(0.0), _subj(trn=140_008_278, py=132_052_680))
    assert note["realized_yoy"]["available"] is True
    assert note["realized_yoy"]["dollars"] == "$8.0M"      # +7,955,598 -> $8.0M
    assert note["realized_yoy"]["pct"] == "+6.02%"
    assert "not a forecast" in note["realized_yoy"]["framing"]


def test_realized_yoy_unavailable_graceful():
    note = _phase_in_note(_Phase(0.0), _subj(py=None))
    assert note["realized_yoy"]["available"] is False
    assert "prior-year transitional value not available" in note["realized_yoy"]["message"]


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
        blob = " ".join([note["mechanism"], note["pending"]["label"],
                         note["realized_yoy"].get("framing", ""),
                         note["pending"].get("caveat") or ""]).lower()
        for banned in ("over-taxation", "over-assessed", "too high", "too low", "drag", "should"):
            assert banned not in blob
