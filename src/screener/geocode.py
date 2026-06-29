"""Address -> BBL resolver (front-door input). NYC Geoclient v2 on api.nyc.gov.

AUTH (non-negotiable):
  * The subscription key is sent as the HTTP header `Ocp-Apim-Subscription-Key`
    (v2). It is NOT an app_id/app_key query pair — that is the legacy portal.
  * The key is read from the GEOCLIENT_API_KEY environment variable (loaded from the
    project .env, which is gitignored). It is NEVER hardcoded and NEVER committed.
  * If the key is missing, the resolver fails with a clear message and does not call out.

Flow: call GET /address with houseNumber, street, and borough OR zip; extract ONLY the
`bbl` field (discard everything else); then validate the BBL against the loaded engine
data BEFORE handing it downstream:
  * not in the class-4 roll  -> out-of-scope (not tax class 4)
  * not office (O*)          -> out_of_scope_v1
  * tax-exempt (curmkttot<=0)-> no-comparison message
  * no geocode / no bbl      -> "address not found" (never a guess)

The resolver hands downstream a validated office BBL, or a clean refusal/error. It never
fabricates or guesses a BBL. No LLM.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import duckdb
import httpx

from . import config
from .comps import REFUSAL_MESSAGES

GEOCLIENT_URL = "https://api.nyc.gov/geoclient/v2/address"
KEY_HEADER = "Ocp-Apim-Subscription-Key"
ENV_VAR = "GEOCLIENT_API_KEY"

# Messages for resolver-specific outcomes (engine refusals reuse comps.REFUSAL_MESSAGES).
RESOLVER_MESSAGES = {
    "address_not_found": "address not found; no BBL could be resolved for the input provided",
    "not_class_4": "out of scope — this parcel is not tax class 4 (commercial)",
    "missing_inputs": "House number, street, and a borough or ZIP are all required to "
                      "identify the address. House number and street alone can match "
                      "multiple boroughs.",
    "geoclient_unauthorized": "Geoclient rejected the subscription key (401). "
                              "Check GEOCLIENT_API_KEY in .env.",
}


class GeoclientConfigError(RuntimeError):
    """Raised when the API key is not configured. Never proceeds without it."""


@dataclass
class ResolveResult:
    ok: bool                    # True only when a validated office BBL is ready downstream
    bbl: str | None
    house_number: str | None
    street: str | None
    borough: str | None
    zip_code: str | None
    bldg_class: str | None
    refused: bool
    reason: str | None          # address_not_found / not_class_4 / out_of_scope_v1 /
                                # subject_tax_exempt / missing_inputs / geoclient_unauthorized
    message: str | None


# --------------------------------------------------------------------------- #
def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (no dependency). Real env vars take precedence."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def get_api_key() -> str:
    """Return the Geoclient subscription key, or raise with a clear message. Never logs it."""
    _load_dotenv(config.REPO_ROOT / ".env")
    key = os.environ.get(ENV_VAR, "").strip()
    if not key:
        raise GeoclientConfigError(
            f"{ENV_VAR} is not set. Add your NYC Geoclient v2 subscription key to the .env "
            f"file at {config.REPO_ROOT / '.env'} (line: {ENV_VAR}=your_key) and retry."
        )
    return key


# --------------------------------------------------------------------------- #
def _geocode_bbl(house_number: str, street: str, borough: str | None,
                 zip_code: str | None, key: str, timeout: float = 30.0) -> tuple[str | None, str | None]:
    """Call Geoclient /address and return (bbl, error_reason). Extracts ONLY bbl."""
    params = {"houseNumber": house_number, "street": street}
    if borough:
        params["borough"] = borough
    elif zip_code:
        params["zip"] = zip_code

    try:
        resp = httpx.get(GEOCLIENT_URL, params=params, headers={KEY_HEADER: key}, timeout=timeout)
    except httpx.HTTPError:
        return None, "address_not_found"

    if resp.status_code in (401, 403):
        return None, "geoclient_unauthorized"
    if resp.status_code != 200:
        return None, "address_not_found"

    try:
        data = resp.json()
    except ValueError:
        return None, "address_not_found"

    # v2 may return the address object flat or under "address"; look for bbl in both.
    node = data.get("address", data) if isinstance(data, dict) else {}
    bbl = (node.get("bbl") if isinstance(node, dict) else None) or (
        data.get("bbl") if isinstance(data, dict) else None)
    bbl = str(bbl).strip() if bbl else None
    if not bbl:
        return None, "address_not_found"
    return bbl, None


def _validate_bbl(con: duckdb.DuckDBPyConnection, bbl: str, *,
                  house_number=None, street=None, borough=None, zip_code=None,
                  comp_table: str = "parcels") -> ResolveResult:
    """Validate a resolved BBL against the loaded engine data. Pure DB checks."""
    base = dict(bbl=bbl, house_number=house_number, street=street, borough=borough,
                zip_code=zip_code)
    rows = con.execute(
        f"""SELECT parcel_id, bldg_class, curmkttot FROM {comp_table}
            WHERE TRY_CAST(parcel_id AS BIGINT) = TRY_CAST(? AS BIGINT)""",
        [bbl],
    ).fetchall()

    # Not in the class-4 roll -> not tax class 4.
    if not rows:
        return ResolveResult(ok=False, bldg_class=None, refused=True,
                             reason="not_class_4", message=RESOLVER_MESSAGES["not_class_4"], **base)
    _, bldg_class, curmkttot = rows[0]

    if not (bldg_class or "").startswith("O"):
        return ResolveResult(ok=False, bldg_class=bldg_class, refused=True,
                             reason="out_of_scope_v1", message=REFUSAL_MESSAGES["out_of_scope_v1"], **base)
    if curmkttot is None or curmkttot <= 0:
        return ResolveResult(ok=False, bldg_class=bldg_class, refused=True,
                             reason="subject_tax_exempt", message=REFUSAL_MESSAGES["subject_tax_exempt"], **base)

    return ResolveResult(ok=True, bldg_class=bldg_class, refused=False,
                         reason=None, message=None, **base)


def resolve_address(house_number: str, street: str, *, borough: str | None = None,
                    zip_code: str | None = None, con: duckdb.DuckDBPyConnection,
                    key: str | None = None, timeout: float = 30.0) -> ResolveResult:
    """Resolve an address to a validated office BBL, or a clean refusal/error.

    Requires houseNumber, street, and one of borough or zip. Never guesses a BBL.
    """
    base = dict(bbl=None, house_number=house_number, street=street, borough=borough,
                zip_code=zip_code, bldg_class=None)
    if not house_number or not street or not (borough or zip_code):
        return ResolveResult(ok=False, refused=True, reason="missing_inputs",
                             message=RESOLVER_MESSAGES["missing_inputs"], **base)

    key = key or get_api_key()
    bbl, err = _geocode_bbl(house_number, street, borough, zip_code, key, timeout)
    if err:
        msg = RESOLVER_MESSAGES.get(err, RESOLVER_MESSAGES["address_not_found"])
        return ResolveResult(ok=False, refused=True, reason=err, message=msg, **base)

    return _validate_bbl(con, bbl, house_number=house_number, street=street,
                         borough=borough, zip_code=zip_code)
