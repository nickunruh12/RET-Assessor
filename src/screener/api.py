"""Thin FastAPI backend + single server-rendered page. NO new engine logic — it runs
the existing pipeline (geocode -> resolve -> comps -> stats -> variance) and assembles
the result for the page. RUNG 3 is a separate opt-in endpoint, off by default.

Run locally (not deployed):
    PYTHONPATH=src .venv/bin/uvicorn screener.api:app --reload
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config
from .comps import select_comps
from .expense_ratio import run_expense_ratio
from .geocode import GeoclientConfigError, ResolveResult, _validate_bbl, resolve_address
from .jurisdiction import CompCriteria, get_jurisdiction
from .rung3 import run_rung3
from .serialize import (
    DISCLAIMER,
    RADIUS_MAX,
    RADIUS_MIN,
    build_expense_ratio_view,
    build_rung3_view,
    build_screen_view,
)

_HERE = Path(__file__).resolve().parent
app = FastAPI(title="NYC Class-4 Assessment Screen")
app.mount("/static", StaticFiles(directory=_HERE / "static"), name="static")
templates = Jinja2Templates(directory=_HERE / "templates")

CRITERIA = CompCriteria.load()
JURIS = get_jurisdiction(CRITERIA.jurisdiction)


def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(config.DB_PATH), read_only=True)


def _resolve_input(con, *, bbl, house_number, street, borough, zip_code) -> ResolveResult | None:
    """Produce a ResolveResult from a BBL or an address.

    Returns None ONLY when truly nothing was submitted (no BBL, all address fields blank) —
    the clean empty state. A PARTIAL address (any address field typed but the
    house+street+(borough|zip) requirement unmet) is handed to resolve_address, which returns
    the existing missing_inputs refusal (before any key/network access) instead of a silent
    None that would blank the page.
    """
    if bbl:
        return _validate_bbl(con, bbl.strip())
    if house_number or street or borough or zip_code:
        return resolve_address((house_number or "").strip(), (street or "").strip(),
                               borough=(borough or None), zip_code=(zip_code or None), con=con)
    return None


def _effective_criteria(radius: str):
    """Resolve the radius override. 'default'/'' -> auto 0.5->1.0 mi (unchanged criteria).
    A number -> fixed search radius (start = cap = R), clamped to [RADIUS_MIN, RADIUS_MAX]."""
    sel = (radius or "").strip().lower()
    if sel in ("", "default"):
        return CRITERIA, "default"
    try:
        r = float(sel)
    except ValueError:
        return CRITERIA, "default"
    r = max(RADIUS_MIN, min(RADIUS_MAX, r))
    crit = CRITERIA.model_copy(update={"radius_start_miles": r, "radius_cap_miles": r})
    return crit, f"{r:g}"


def _fixed_radius_criteria(radius: float):
    """Criteria with a fixed search radius (start = cap = clamped R). Used for both the
    full screen override and the lightweight live count — same comp definition."""
    r = max(RADIUS_MIN, min(RADIUS_MAX, radius))
    return CRITERIA.model_copy(update={"radius_start_miles": r, "radius_cap_miles": r}), r


def _screen_view(con, *, bbl, house_number, street, borough, zip_code, radius=""):
    """Returns (result_dict_or_None, resolved_bbl_or_None). resolved_bbl is the parcel
    actually screened, used to repopulate the form on re-runs that carried only the BBL."""
    try:
        rr = _resolve_input(con, bbl=bbl, house_number=house_number, street=street,
                            borough=borough, zip_code=zip_code)
    except GeoclientConfigError as e:
        return {"status": "refused", "stage": "resolve", "reason": "geoclient_unconfigured",
                "message": str(e), "disclaimer": DISCLAIMER, "subject": None, "context": None,
                "rung3": {"enabled": False}}, None
    if rr is None:
        return None, None
    crit, radius_selection = _effective_criteria(radius)
    result = build_screen_view(con, crit, JURIS, resolve=rr, radius_selection=radius_selection)
    return result, rr.bbl


def _build_form(con, effective_bbl, typed: dict) -> dict:
    """Persist the screened parcel's identity in the input bar. The address is looked up
    from the BBL in the roll (PLUTO fallback) so it stays populated even when the re-run
    URL carried only bbl + radius. Falls back to the typed values when there is no BBL."""
    form = {"bbl": (effective_bbl or typed.get("bbl") or "").strip(),
            "house_number": (typed.get("house_number") or "").strip(),
            "street": (typed.get("street") or "").strip(),
            "borough": (typed.get("borough") or "").strip(),
            "zip": (typed.get("zip") or "").strip()}
    if not effective_bbl:
        return form
    row = con.execute(
        """SELECT parcel_id, house_number, street_name, zip_code, pluto_address
           FROM parcels WHERE parcel_id = ?""", [effective_bbl.strip()],
    ).fetchone()
    if not row:                      # resolved BBL not in the class-4 roll (out of scope)
        form["bbl"] = effective_bbl.strip()
        return form
    pid, hn, st, zp, paddr = row
    house, street = (hn or "").strip(), (st or "").strip()
    if not house and not street and paddr:    # roll address absent -> PLUTO fallback
        street = paddr.strip()
    form.update({"bbl": pid, "house_number": house, "street": street,
                 "borough": JURIS.borough_of(pid), "zip": (zp or "").strip()})
    return form


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "page.html", {
        "result": None, "result_json": "null", "disclaimer": DISCLAIMER, "form": {},
    })


@app.get("/screen", response_class=HTMLResponse)
def screen(request: Request, bbl: str = "", house_number: str = "", street: str = "",
           borough: str = "", zip: str = "", radius: str = ""):
    typed = {"bbl": bbl, "house_number": house_number, "street": street, "borough": borough, "zip": zip}
    with _con() as con:
        result, resolved_bbl = _screen_view(con, bbl=bbl, house_number=house_number, street=street,
                                            borough=borough, zip_code=zip, radius=radius)
        form = _build_form(con, resolved_bbl or bbl, typed)
    return templates.TemplateResponse(request, "page.html", {
        "result": result, "disclaimer": DISCLAIMER, "form": form,
        "result_json": json.dumps(result, default=str) if result else "null",
    })


@app.get("/api/screen")
def api_screen(bbl: str = "", house_number: str = "", street: str = "",
               borough: str = "", zip: str = "", radius: str = ""):
    with _con() as con:
        result, _ = _screen_view(con, bbl=bbl, house_number=house_number, street=street,
                                 borough=borough, zip_code=zip, radius=radius)
    return JSONResponse(result or {"status": "no_input"})


@app.post("/api/rung3")
def api_rung3(bbl: str = Query(...), noi: str = Query(""), enabled: bool = Query(False)):
    with _con() as con:
        result = run_rung3(con, bbl.strip(), noi, enabled=enabled)
    return JSONResponse(build_rung3_view(result))


@app.post("/api/expense_ratio")
def api_expense_ratio(bbl: str = Query(...), opex: str = Query("")):
    with _con() as con:
        result = run_expense_ratio(con, bbl.strip(), opex, CRITERIA)
    return JSONResponse(build_expense_ratio_view(result))


@app.get("/api/comp_count")
def api_comp_count(bbl: str = Query(...), radius: float = Query(...)):
    """Lightweight live-count for the slider drag: qualifying comps at a FIXED radius.
    Reuses the comp definition (select_comps); returns ONLY the count, no stats/payload."""
    crit, r = _fixed_radius_criteria(radius)
    with _con() as con:
        cs = select_comps(con, bbl.strip(), JURIS, crit)
    # On success cs.count is the selected set (>= min). On an insufficient-comps refusal
    # cs.count is 0, but the qualifying pool that fell short is candidates_within_cap —
    # that is the honest "how many qualify at this radius" for the dead-zone preview.
    count = cs.count if not cs.refused else cs.candidates_within_cap
    return JSONResponse({
        "radius": round(r, 2),
        "count": count,
        "refused": cs.refused,
        "below_min": count < crit.min_comp_count,
        "min_comp_count": crit.min_comp_count,
        "note": cs.note,
    })
