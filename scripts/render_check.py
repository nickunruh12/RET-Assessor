#!/usr/bin/env python3
"""Render check for the output view. Produces the full server-rendered page for four
subjects and enforces the no-verdict rendering rules over the rendered HTML + the
served CSS/JS.

  (a) dense Manhattan office   (b) fallback-heavy (low-exact caution)
  (c) no-SF (assessed+tax render, $/SF refuses)   (d) tax-exempt (no-comparison message)

Confirms: no alert coloring, no threshold lines/zones, no characterizing labels,
disclaimer present and above the numbers, provenance accessible, RUNG 3 off by default.

Scans are run AFTER stripping source comments — the only occurrences of words like
"red"/"box plot"/"threshold" in the codebase are in comments documenting these very
constraints, which are not delivered as visual encoding.

    PYTHONPATH=src python scripts/render_check.py
"""
from __future__ import annotations

import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from screener.api import app  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "render_check"
STATIC = ROOT / "src" / "screener" / "static"

SUBJECTS = [
    ("a_dense", "1000090001", "ok"),
    ("b_fallback", "2023070046", "ok"),
    ("c_no_sf", "3053480042", "ok"),
    ("d_tax_exempt", "1000380001", "refused"),
]

# Characterizing verdict words that must never appear in visible output (per the spec's
# banned list). The variance comparatives "higher than"/"lower than" are allowed and do
# not match (\bhigh\b != "higher").
BANNED_WORDS = [
    r"\boutlier", r"\baberrant\b", r"\bflagged\b", r"\balarm\b",
    r"\bover-?assessed\b", r"\bunder-?assessed\b", r"\boverpriced\b", r"\bunderpriced\b",
    r"\babove market\b", r"\bbelow market\b", r"\bnormal range\b",
    r"\bhigh\b", r"\blow\b",
]
BANNED_COLOR = [r"\bred\b", r"\bamber\b", r"\borange\b", r"\bcrimson\b", r"\btomato\b",
                r"\bsalmon\b", r"\bgreen\b", r"\blime\b", r"\bdanger\b", r"\bwarning\b",
                r"#f00\b", r"#ff0000\b"]
BANNED_CHART = [r"annotation", r"threshold", r"box ?plot", r"\bzone\b", r"shad(e|ing)",
                r"normal range"]


def strip_css(s): return re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
def strip_js(s): return re.sub(r"//[^\n]*", " ", re.sub(r"/\*.*?\*/", " ", s, flags=re.S))
def strip_html_comments(s): return re.sub(r"<!--.*?-->", " ", s, flags=re.S)


def scan(text, patterns):
    return sorted({re.search(p, text, re.I).group(0).lower()
                   for p in patterns if re.search(p, text, re.I)})


def main():
    OUT.mkdir(exist_ok=True)
    client = TestClient(app)
    css = strip_css((STATIC / "style.css").read_text())
    js = strip_js((STATIC / "app.js").read_text())

    print("=" * 78)
    print("STATIC ASSET SCAN (served CSS + JS, comments stripped)")
    color_hits = scan(css, BANNED_COLOR) + scan(js, BANNED_COLOR)
    chart_hits = scan(js, BANNED_CHART)
    print(f"  alert/good-bad colors actually used: {color_hits or 'NONE ✓'}")
    print(f"  threshold/zone/box-plot/annotation in chart code: {chart_hits or 'NONE ✓'}")
    ok = not color_hits and not chart_hits

    print("\n" + "=" * 78)
    print("PER-SUBJECT RENDER CHECK")
    for label, bbl, status in SUBJECTS:
        raw = client.get("/screen", params={"bbl": bbl}).text
        (OUT / f"{label}.html").write_text(raw)
        html = strip_html_comments(raw)            # scan visible content, not comments

        disc_i = html.find("not a verdict, not tax advice")
        first_subject = html.find('class="subject"')
        first_money = html.find("$")
        disclaimer_above = disc_i != -1 and (first_subject == -1 or disc_i < first_subject) \
            and (first_money == -1 or disc_i < first_money)

        word_hits = scan(html, BANNED_WORDS)

        print(f"\n  [{label}]  BBL {bbl}  (status: {status})")
        print(f"    disclaimer above the numbers: {disclaimer_above}")
        print(f"    banned characterizing words:  {word_hits or 'NONE ✓'}")
        ok = ok and disclaimer_above and not word_hits

        if status == "ok":
            # RUNG 3 + expense ratio: always-visible inputs, but NO computed result on load
            # (opt-in: nothing computed until the user clicks Compute).
            inputs_present = ('id="rung3-noi"' in raw and 'id="rung3-go"' in raw
                              and 'id="opex-input"' in raw and 'id="opex-go"' in raw)
            no_result_on_load = "implies a" not in raw.lower() and "operating expense you provided" not in raw.lower()
            prov = "Provenance — Every Figure" in raw
            print(f"    user-input tools present, no result on load: {inputs_present and no_result_on_load}")
            print(f"    provenance accessible:        {prov}")
            ok = ok and inputs_present and no_result_on_load and prov
            # expense-ratio benchmark note for office subjects (NYC + office configured)
            note = ("40–50% = typical range" in raw and "office building in New York City" in raw)
            print(f"    expense benchmark note (NYC office): {note}")
            ok = ok and note
        else:
            tools_absent = 'id="rung3-noi"' not in raw and 'id="opex-input"' not in raw
            print(f"    user-input tools not offered on refusal: {tools_absent}")
            ok = ok and tools_absent

        if label == "c_no_sf":
            psf = ("gross building area missing for this parcel" in raw
                   and "chart-assessed_value_market" in raw)
            print(f"    $/SF refuses, assessed renders: {psf}")
            ok = ok and psf
        if label == "d_tax_exempt":
            em = "no positive market value (tax-exempt)" in raw
            print(f"    tax-exempt no-comparison message: {em}")
            ok = ok and em
        if label == "b_fallback":
            cau = "largely adjacent-class" in raw
            print(f"    low-exact caution shown:      {cau}")
            ok = ok and cau

        if word_hits:
            for p in BANNED_WORDS:
                m = re.search(p, html, re.I)
                if m:
                    print(f"      hit {m.group(0)!r}: …{html[max(0,m.start()-40):m.end()+30]}…")

    print("\n" + "=" * 78)
    print(f"RENDER CHECK: {'ALL CLEAN ✓' if ok else 'FAILURES ABOVE ✗'}")
    print(f"Full pages written to {OUT}/")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
