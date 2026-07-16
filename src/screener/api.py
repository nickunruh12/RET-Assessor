"""Thin FastAPI backend + single server-rendered page. NO new engine logic — it runs
the existing pipeline (geocode -> resolve -> comps -> stats -> variance) and assembles
the result for the page. RUNG 3 is a separate opt-in endpoint, off by default.

Run locally (not deployed):
    PYTHONPATH=src .venv/bin/uvicorn screener.api:app --reload
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

import duckdb
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import config
from .bootstrap import ensure_db_present
from .custom_comps import build_custom_screen_view, resolve_subject, validate_comp
from .comps import select_comps
from .expense_ratio import run_expense_ratio
from .geocode import GeoclientConfigError, ResolveResult, _validate_bbl, resolve_address
from .jurisdiction import CompCriteria, get_jurisdiction
from .rung3 import run_rung3
from .retail_comps import build_retail_screen_view, select_retail_comps
from .industrial_comps import build_industrial_screen_view, select_industrial_comps
from .serialize import (
    DISCLAIMER,
    RADIUS_MAX,
    RADIUS_MIN,
    build_expense_ratio_view,
    build_rung3_view,
    build_screen_view,
)

_HERE = Path(__file__).resolve().parent


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Deployment bootstrap: ensure the DuckDB is present BEFORE any request opens a connection.
    # Downloads it from SCREENER_DB_URL if missing; a strict no-op when it already exists (local
    # dev). Runs at app startup, before the first _con(). Never touches engine/comp/stats logic.
    ensure_db_present()
    yield


app = FastAPI(title="NYC Class-4 Assessment Screen", lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=_HERE / "static"), name="static")
templates = Jinja2Templates(directory=_HERE / "templates")


def _asset_version() -> str:
    """Short content hash of the static assets, appended to their URLs as ?v=... so a
    browser ALWAYS fetches the current app.js / style.css after a change instead of serving
    a stale cached copy (the bug behind 'edited the chart but the browser shows the old one').
    Computed once at import from file contents."""
    import hashlib

    h = hashlib.sha1()
    for name in ("app.js", "style.css"):
        p = _HERE / "static" / name
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()[:10]


ASSET_VERSION = _asset_version()

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


def _effective_radius_selection(radius: str) -> str:
    """Resolve the slider state to a label for retail/industrial: 'default' (auto) or a clamped
    '%g' string R. The retail/industrial view builders turn a numeric R into a radius_override
    that BOUNDS their cascade — the same mechanism the live comp_count uses, so the two match."""
    sel = (radius or "").strip().lower()
    if sel in ("", "default"):
        return "default"
    try:
        r = float(sel)
    except ValueError:
        return "default"
    return f"{max(RADIUS_MIN, min(RADIUS_MAX, r)):g}"


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
    # RETAIL LIVE SWITCH — a resolved class-4 K-code (retail) routes to the SAME retail engine
    # as the /retail_screen test route (byte-identical: same call, no resolve/radius plumbing).
    # This lifts the out_of_scope_v1 refusal for K-codes ONLY; the wall still holds for every
    # other non-office class (R condos, V vacant, G garage, U utility), which keep refusing
    # because they do not start with "K". The K-code resolves to out_of_scope_v1 in the office
    # resolver (non-"O"), but carries its bldg_class + bbl, which is all the retail engine needs.
    if (rr.bldg_class or "").startswith("K"):
        return build_retail_screen_view(
            con, CRITERIA, JURIS, bbl=rr.bbl,
            radius_selection=_effective_radius_selection(radius)), rr.bbl
    # INDUSTRIAL LIVE SWITCH — a resolved class-4 F-code (industrial) routes to the SAME
    # industrial engine as the /industrial_screen test route (byte-identical: same call, no
    # resolve/radius plumbing). Same K-only pattern: F-codes are intercepted UPSTREAM; the broad
    # out_of_scope_v1 gate is untouched, so every non-office/non-K/non-F class (R condos, V
    # vacant, G garage, U utility) keeps refusing. The F-code resolves to out_of_scope_v1 in the
    # office resolver (non-"O") but carries its bldg_class + bbl, all the industrial engine needs.
    if (rr.bldg_class or "").startswith("F"):
        return build_industrial_screen_view(
            con, CRITERIA, JURIS, bbl=rr.bbl,
            radius_selection=_effective_radius_selection(radius)), rr.bbl
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


# Named screening MODES — the front-door mode-fork. "auto_generate" (the only mode today) runs
# the existing engine: the tool selects comps by MEASURED property type, size, and location.
# FUTURE: "custom_comps" — the user supplies their own comp list, bypassing selection — slots in
# as a branch in the screen handlers (see the marked fork), NOT a restructure. Property type is
# ALWAYS measured from the parcel, never user-selected (hard architectural boundary — no type
# dropdown, ever).
SCREEN_MODES = ("auto_generate", "custom_comps")   # custom_comps has its own /custom flow


def _resolve_mode(mode: str) -> str:
    """Validate the requested screening mode; unknown/blank -> auto_generate (safe default)."""
    return mode if mode in SCREEN_MODES else "auto_generate"


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    """Welcome / landing page — the front door. 'Get Started' enters the tool in auto_generate
    mode (/screen?mode=auto_generate)."""
    return templates.TemplateResponse(request, "welcome.html", {
        "disclaimer": DISCLAIMER, "asset_version": ASSET_VERSION,
    })


@app.get("/screen", response_class=HTMLResponse)
def screen(request: Request, bbl: str = "", house_number: str = "", street: str = "",
           borough: str = "", zip: str = "", radius: str = "", mode: str = "auto_generate"):
    mode = _resolve_mode(mode)
    typed = {"bbl": bbl, "house_number": house_number, "street": street, "borough": borough, "zip": zip}
    with _con() as con:
        # --- MODE FORK ---------------------------------------------------------------------
        # auto_generate: the tool selects comps by measured type/size/location (the live engine).
        # FUTURE: custom_comps mode branches HERE — screen against a user-supplied comp list,
        # bypassing selection (not built; see BACKLOG.md). Property type stays MEASURED either way.
        result, resolved_bbl = _screen_view(con, bbl=bbl, house_number=house_number, street=street,
                                            borough=borough, zip_code=zip, radius=radius)
        form = _build_form(con, resolved_bbl or bbl, typed)
    return templates.TemplateResponse(request, "page.html", {
        "result": result, "disclaimer": DISCLAIMER, "form": form, "mode": mode,
        "result_json": json.dumps(result, default=str) if result else "null",
        "asset_version": ASSET_VERSION,
    })


@app.get("/api/retail_screen")
def api_retail_screen(bbl: str = ""):
    """Direct retail-engine route, kept for debugging. Retail is now LIVE on the public
    /screen + /api/screen routes (K-codes route here automatically); this route screens a
    K-code by BBL with no address resolution, producing byte-identical output."""
    b = bbl.strip()
    if not b:
        return JSONResponse({"status": "no_input"})
    with _con() as con:
        return JSONResponse(build_retail_screen_view(con, CRITERIA, JURIS, bbl=b))


@app.get("/retail_screen", response_class=HTMLResponse)
def retail_screen(request: Request, bbl: str = ""):
    """Direct retail-screen render, kept for debugging. Retail is now LIVE on public /screen;
    this route renders a K-code by BBL with no address resolution (byte-identical engine)."""
    b = bbl.strip()
    with _con() as con:
        result = build_retail_screen_view(con, CRITERIA, JURIS, bbl=b) if b else None
    return templates.TemplateResponse(request, "page.html", {
        "result": result, "disclaimer": DISCLAIMER, "form": {"bbl": b},
        "result_json": json.dumps(result, default=str) if result else "null",
        "asset_version": ASSET_VERSION,
    })


@app.get("/api/industrial_screen")
def api_industrial_screen(bbl: str = ""):
    """Direct industrial-engine route, kept for debugging. Industrial is now LIVE on the public
    /screen + /api/screen routes (F-codes route here automatically); this route screens an
    F-code by BBL with no address resolution, producing byte-identical output."""
    b = bbl.strip()
    if not b:
        return JSONResponse({"status": "no_input"})
    with _con() as con:
        return JSONResponse(build_industrial_screen_view(con, CRITERIA, JURIS, bbl=b))


@app.get("/industrial_screen", response_class=HTMLResponse)
def industrial_screen(request: Request, bbl: str = ""):
    """Direct industrial-screen render, kept for debugging. Industrial is now LIVE on public
    /screen; this route renders an F-code by BBL with no address resolution (byte-identical)."""
    b = bbl.strip()
    with _con() as con:
        result = build_industrial_screen_view(con, CRITERIA, JURIS, bbl=b) if b else None
    return templates.TemplateResponse(request, "page.html", {
        "result": result, "disclaimer": DISCLAIMER, "form": {"bbl": b},
        "result_json": json.dumps(result, default=str) if result else "null",
        "asset_version": ASSET_VERSION,
    })


@app.get("/api/screen")
def api_screen(bbl: str = "", house_number: str = "", street: str = "",
               borough: str = "", zip: str = "", radius: str = "", mode: str = "auto_generate"):
    _resolve_mode(mode)   # MODE FORK: auto_generate runs the engine below; custom_comps branches
                          # here later (not built). The JSON result is identical across modes today.
    with _con() as con:
        result, _ = _screen_view(con, bbl=bbl, house_number=house_number, street=street,
                                 borough=borough, zip_code=zip, radius=radius)
    return JSONResponse(result or {"status": "no_input"})


class CustomScreenRequest(BaseModel):
    subject_bbl: str
    comp_bbls: list[str] = []
    fill: str = "none"                 # "none" (thin/expose options) | "autofill" (fill to 8)


@app.post("/api/v1/custom_screen")
def api_custom_screen(req: CustomScreenRequest):
    """Manual-override lane: screen a user-supplied comp set (NOT auto-selected). New path — it
    does not touch _screen_view or the auto-selectors, so /api/screen stays byte-identical."""
    with _con() as con:
        result = build_custom_screen_view(
            con, CRITERIA, JURIS, subject_bbl=req.subject_bbl.strip(),
            comp_bbls=req.comp_bbls, fill=(req.fill or "none").strip().lower())
    return JSONResponse(result)


@app.get("/custom", response_class=HTMLResponse)
def custom(request: Request, bbl: str = "", house_number: str = "", street: str = "",
           borough: str = "", zip: str = "", via: str = ""):
    """Custom-comps wizard (step 2/3). Resolves the subject with the SAME resolver the auto path
    uses, then renders the shared subject-facts partial for confirmation + the comp-entry step.

    `via` names the CLICKED button ('address' | 'bbl'): the clicked side is the ONLY input used —
    the other field is ignored, never a silent fallback. An empty clicked input gets an inline
    error naming that input. No `via` (deep link / old URL) keeps the permissive behavior."""
    typed = {"bbl": bbl, "house_number": house_number, "street": street, "borough": borough, "zip": zip}
    ctx = {"disclaimer": DISCLAIMER, "asset_version": ASSET_VERSION, "typed": typed,
           "subject": None, "subject_bbl": None, "refusal": None, "entry_error": None,
           "asset_type": None, "autofill_available": False,
           "out_of_scope_for_auto": False, "scope_notice": None}
    if via == "address":
        bbl = ""                                        # the click disambiguates: address only
        if not (house_number.strip() or street.strip()):
            ctx["entry_error"] = "Enter an address"
            return templates.TemplateResponse(request, "custom.html", ctx)
    elif via == "bbl":
        house_number = street = borough = zip = ""      # the click disambiguates: BBL only
        if not bbl.strip():
            ctx["entry_error"] = "Enter a BBL"
            return templates.TemplateResponse(request, "custom.html", ctx)
    if bbl or house_number or street:
        with _con() as con:
            rr = _resolve_input(con, bbl=bbl, house_number=house_number, street=street,
                                borough=borough, zip_code=zip)
            resolved = rr.bbl if rr is not None else None
            if not resolved:
                ctx["refusal"] = "Could not resolve that input to a parcel. Check the address or BBL."
            else:
                r = resolve_subject(con, CRITERIA, JURIS, resolved)
                if r["status"] == "ok":
                    ctx.update(subject=r["subject"], subject_bbl=resolved,
                               asset_type=r["asset_type"], autofill_available=r["autofill_available"],
                               out_of_scope_for_auto=r["out_of_scope_for_auto"],
                               scope_notice=r["scope_notice"])
                else:
                    ctx["refusal"] = r["message"]
    return templates.TemplateResponse(request, "custom.html", ctx)


class CustomValidateRequest(BaseModel):
    subject_bbl: str
    bbl: str = ""                      # comp by BBL …
    house_number: str = ""             # … or by address (resolved with the same machinery the
    street: str = ""                   #     auto path uses: _resolve_input -> resolve_address)
    borough: str = ""
    zip: str = ""
    comp_bbls: list[str] = []          # back-compat: comp_bbls[0] honored when bbl/address absent


@app.post("/api/v1/custom_validate_comp")
def api_custom_validate_comp(req: CustomValidateRequest):
    """Per-comp validation for the wizard: accepts a BBL OR an address; either way the SAME
    per-comp validation fires on the resolved BBL."""
    with _con() as con:
        comp = (req.bbl or (req.comp_bbls[0] if req.comp_bbls else "")).strip()
        if not comp and (req.house_number.strip() or req.street.strip()):
            try:
                rr = _resolve_input(con, bbl="", house_number=req.house_number, street=req.street,
                                    borough=req.borough, zip_code=req.zip)
            except GeoclientConfigError as e:
                return JSONResponse({"bbl": None, "status": "not_found", "valid": False,
                                     "reason": str(e)})
            comp = (rr.bbl if rr is not None and rr.bbl else "")
            if not comp:
                return JSONResponse({"bbl": None, "status": "not_found", "valid": False,
                                     "reason": "address not found; no BBL could be resolved"})
        if not comp:
            return JSONResponse({"bbl": None, "status": "not_found", "valid": False,
                                 "reason": "enter a BBL or an address"})
        return JSONResponse(validate_comp(con, CRITERIA, JURIS, req.subject_bbl.strip(), comp))


@app.get("/custom_result", response_class=HTMLResponse)
def custom_result(request: Request, subject: str = "", comps: str = "", fill: str = "none"):
    """Render the custom-comps screen through the SHARED output template (page.html). The custom
    layers (not-vetted stamp, origin column, mix) are gated in the template on product=custom_comps."""
    comp_bbls = [b.strip() for b in comps.split(",") if b.strip()]
    with _con() as con:
        result = build_custom_screen_view(con, CRITERIA, JURIS, subject_bbl=subject.strip(),
                                          comp_bbls=comp_bbls, fill=(fill or "none").strip().lower())
    return templates.TemplateResponse(request, "page.html", {
        "result": result, "disclaimer": DISCLAIMER, "form": {"bbl": subject}, "mode": "custom_comps",
        "result_json": json.dumps(result, default=str), "asset_version": ASSET_VERSION,
    })


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
    Routes to the SAME selector the screen uses — office (O), retail (K), industrial (F) —
    mirroring the _screen_view dispatch, so the live count matches the rendered comp set
    instead of always 0 for K/F. Returns ONLY the count, no stats/payload."""
    b = bbl.strip()
    r = max(RADIUS_MIN, min(RADIUS_MAX, radius))
    with _con() as con:
        row = con.execute(
            "SELECT bldg_class FROM parcels WHERE parcel_id = ?", [b]).fetchone()
        bc = (row[0] if row else "") or ""
        # Same class dispatch as _screen_view, and the SAME radius_override mechanism the screen
        # uses at this radius — so the live count equals the comp set the screen would render.
        if bc.startswith("K"):
            cs, _ = select_retail_comps(con, b, JURIS, CRITERIA, radius_override=r)
            min_c = CRITERIA.min_comp_count
        elif bc.startswith("F"):
            cs, _ = select_industrial_comps(con, b, JURIS, CRITERIA, radius_override=r)
            min_c = (CRITERIA.industrial_config or {}).get("min_comp_count", CRITERIA.min_comp_count)
        else:
            crit, r = _fixed_radius_criteria(radius)
            cs = select_comps(con, b, JURIS, crit)
            min_c = crit.min_comp_count
    # On success cs.count is the selected set (>= min). On an insufficient-comps refusal
    # cs.count is 0, but the qualifying pool that fell short is candidates_within_cap —
    # that is the honest "how many qualify at this radius" for the dead-zone preview.
    count = cs.count if not cs.refused else cs.candidates_within_cap
    return JSONResponse({
        "radius": round(r, 2),
        "count": count,
        "refused": cs.refused,
        "below_min": count < min_c,
        "min_comp_count": min_c,
        "note": cs.note,
    })
