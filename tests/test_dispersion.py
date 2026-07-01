"""Descriptive spread stats under each chart: ±1 SD band, IQR (middle 50%), CV%.
Descriptive only — population SD, no projection/inference/verdict. Computed from the SAME
comp value list that feeds each chart (per-SF list already excludes no-SF comps).
"""
import statistics

from screener.serialize import DISPERSION_CAVEAT, _dispersion_stats, _money

WHOLE = "$ (market value)"          # any unit string WITHOUT 'gross_sf' -> whole dollars
PSF = "$ / gross_sf"                # 'gross_sf' in unit -> 2 dp


def test_population_sd_band_and_cv_exact():
    d = _dispersion_stats([10, 20, 30, 40], WHOLE)
    sd = statistics.pstdev([10, 20, 30, 40])           # population SD = 11.1803...
    assert d["cv"] == f"relative spread (CV): {sd / 25 * 100:.2f}%" == "relative spread (CV): 44.72%"
    assert d["sd_band"] == (f"±1 SD: {_money(25 - sd, WHOLE)} – {_money(25 + sd, WHOLE)} "
                            f"(SD {_money(sd, WHOLE)})")


def test_iqr_is_p25_p75_inclusive():
    vals = [100, 200, 300, 400, 500]
    q1, _q2, q3 = statistics.quantiles(vals, n=4, method="inclusive")
    d = _dispersion_stats(vals, WHOLE)
    assert d["iqr"] == f"Middle 50% of comps: {_money(q1, WHOLE)} – {_money(q3, WHOLE)}"


def test_psf_unit_two_decimals_with_dollar_sign():
    d = _dispersion_stats([100.0, 200.0], PSF)
    assert "$100.00" in d["sd_band"] and "$200.00" in d["sd_band"]   # 2 dp + $ sign
    assert d["iqr"].startswith("Middle 50% of comps: $")


def test_whole_dollar_unit_no_decimals():
    d = _dispersion_stats([1_000_000, 3_000_000], WHOLE)
    assert ".00" not in d["sd_band"]          # whole dollars, no decimals
    assert "$" in d["sd_band"]


def test_cv_guard_returns_na_when_mean_not_positive():
    d = _dispersion_stats([-2, -1, 1, 2], WHOLE)   # mean = 0
    assert d["cv"] == "relative spread (CV): n/a"


def test_none_when_fewer_than_two_values():
    assert _dispersion_stats([5], WHOLE) is None
    assert _dispersion_stats([], WHOLE) is None


def test_only_three_metrics_no_variance_mode_zscore():
    d = _dispersion_stats([10, 20, 30, 40], WHOLE)
    assert set(d) == {"sd_band", "iqr", "cv"}      # exactly the three approved metrics


def test_caveat_avoids_banned_outlier_word():
    # the reliability caveat preserves meaning without the banned word "outlier"
    assert "outlier" not in DISPERSION_CAVEAT.lower()
    assert "extreme values" in DISPERSION_CAVEAT and "middle-50%" in DISPERSION_CAVEAT
