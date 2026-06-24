"""Phase-In Note: readable variable names + SIGN-dependent MECHANISM text (no verdict)."""
from screener.serialize import _phase_in_note


class _Phase:
    def __init__(self, v, m=0.0, n=10):
        self.subject_value = v
        self.median = m
        self.n = n


def test_positive_gap_branch():
    note = _phase_in_note(_Phase(0.05))
    assert "positive gap" in note["mechanism"] and "ramping up" in note["mechanism"]


def test_negative_gap_branch():
    note = _phase_in_note(_Phase(-0.05))
    assert "negative gap" in note["mechanism"] and "ramping down" in note["mechanism"]


def test_near_zero_branch():
    note = _phase_in_note(_Phase(0.0))
    assert "fully phased in" in note["mechanism"]


def test_unavailable_branch():
    note = _phase_in_note(_Phase(None))
    assert "unavailable" in note["mechanism"]


def test_readable_formula_no_raw_columns():
    note = _phase_in_note(_Phase(0.05))
    assert note["formula"] == ("(actual assessed value − transitional assessed value) ÷ "
                               "actual assessed value")
    assert "curacttot" not in note["formula"] and "curtrntot" not in note["formula"]


def test_fixed_descriptive_footer():
    assert _phase_in_note(_Phase(0.05))["footer"] == \
        "Descriptive only — not a verdict on the assessment."


def test_no_judgment_words_in_any_branch():
    for v in (0.05, -0.05, 0.0, None):
        m = _phase_in_note(_Phase(v))["mechanism"].lower()
        for banned in ("over-taxation", "over-assessed", "too high", "too low", "drag",
                       "should", "overpaying"):
            assert banned not in m
