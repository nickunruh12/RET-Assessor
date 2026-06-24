"""Decimal-precision rules (item 2): PSF $ and % -> exactly 2 dp; whole figures -> 0 dp;
genuine zeros show 0.00 (never suppressed)."""
from screener.serialize import _delta_psf, _delta_sf, _signal_num, _signed_dollar_psf, _signed_pct


def test_percent_two_decimals():
    assert _signed_pct(12.7324) == "+12.73%"
    assert _signed_pct(-3.0051) == "-3.01%"


def test_percent_genuine_zero_shown():
    assert _signed_pct(0) == "0.00%"
    assert _signed_pct(0.004) == "0.00%"        # rounds to zero -> still shown, not blanked


def test_psf_dollar_two_decimals_and_zero():
    assert _signed_dollar_psf(322) == "+$322.00"
    assert _signed_dollar_psf(0.51) == "+$0.51"
    assert _signed_dollar_psf(-5) == "-$5.00"
    assert _signed_dollar_psf(0) == "$0.00"     # genuine zero shown


def test_delta_psf_format():
    assert _delta_psf(322.0, 93.12) == "+$322.00 PSF (+93.12%)"
    assert _delta_psf(0.51, 3.41) == "+$0.51 PSF (+3.41%)"
    assert _delta_psf(0.0, 0.0) == "$0.00 PSF (0.00%)"
    assert _delta_psf(None, 5) == "n/a"


def test_delta_sf_whole_abs_two_decimal_pct():
    assert _delta_sf(374280, 30.8624) == "+374,280 SF (+30.86%)"   # SF whole, % 2 dp


def test_signal_num_precision_by_unit():
    assert _signal_num(418714000.0, "$") == "418,714,000"          # whole $ -> 0 dp
    assert _signal_num(45748256.11, "$ (tax)") == "45,748,256"     # whole $ -> 0 dp
    assert _signal_num(345.3038, "$/gross_sf") == "345.30"         # PSF -> 2 dp
    assert _signal_num(None, "$") == "n/a"
