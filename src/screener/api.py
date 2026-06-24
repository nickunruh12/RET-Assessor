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
from .expense_ratio import run_expense_ratio
from .geocode import GeoclientConfigError, ResolveResult, _validate_bbl, resolve_address
from .jurisdiction import CompCriteria, get_jurisdiction
from .rung3 import run_rung3
from .serialize import (
    DISCLAIMER,
    RADIUS_MAX,
    RADIUS_MIN,
    RADIUS_PRESETS,
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
    """Produce a ResolveResult from either a BBL or an address (or None if no input)."""
    if bbl:
        return _validate_bbl(con, bbl.strip())
    if house_number and street and (borough or zip_code):
        return resolve_address(house_number.strip(), street.strip(),
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
    # Label it as the matching preset string (e.g. 2.0, 1.0) so the control highlights it.
    label = next((p for p in RADIUS_PRESETS if p != "default" and float(p) == r), f"{r:g}")
    return crit, label


def _screen_view(con, *, bbl, house_number, street, borough, zip_code, radius="") -> dict | None:
    try:
        rr = _resolve_input(con, bbl=bbl, house_number=house_number, street=street,
                            borough=borough, zip_code=zip_code)
    except GeoclientConfigError as e:
        return {"status": "refused", "stage": "resolve", "reason": "geoclient_unconfigured",
                "message": str(e), "disclaimer": DISCLAIMER, "subject": None, "context": None,
                "rung3": {"enabled": False}}
    if rr is None:
        return None
    crit, radius_selection = _effective_criteria(radius)
    return build_screen_view(con, crit, JURIS, resolve=rr, radius_selection=radius_selection)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "page.html", {
        "result": None, "result_json": "null", "disclaimer": DISCLAIMER, "form": {},
    })


@app.get("/screen", response_class=HTMLResponse)
def screen(request: Request, bbl: str = "", house_number: str = "", street: str = "",
           borough: str = "", zip: str = "", radius: str = ""):
    with _con() as con:
        result = _screen_view(con, bbl=bbl, house_number=house_number, street=street,
                              borough=borough, zip_code=zip, radius=radius)
    form = {"bbl": bbl, "house_number": house_number, "street": street, "borough": borough, "zip": zip}
    return templates.TemplateResponse(request, "page.html", {
        "result": result, "disclaimer": DISCLAIMER, "form": form,
        "result_json": json.dumps(result, default=str) if result else "null",
    })


@app.get("/api/screen")
def api_screen(bbl: str = "", house_number: str = "", street: str = "",
               borough: str = "", zip: str = "", radius: str = ""):
    with _con() as con:
        result = _screen_view(con, bbl=bbl, house_number=house_number, street=street,
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
