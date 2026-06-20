"""Locked constants and dataset identifiers. Single source of truth for the engine.

Every value here traces to a dated entry in DECISIONS.md. Do not edit without a
corresponding decision. Tunables are flagged as such.
"""
from __future__ import annotations

from pathlib import Path

# --- Repo layout ---
REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "raw"
DB_PATH = REPO_ROOT / "screener.duckdb"

# --- Datasets (DECISIONS.md, 2026-06-19) ---
SODA_BASE = "https://data.cityofnewyork.us/resource/{dataset}.json"

ROLL_DATASET = "8y4t-faws"   # DOF Property Valuation & Assessment Data (classes 1-4)
PLUTO_DATASET = "64uk-42ks"  # DCP PLUTO — physical characteristics, BldgArea

# --- Scope (LOCKED) ---
TAX_CLASS = "4"              # commercial only, v1
ROLL_YEAR = "2027"          # FY2027 final roll; 263,023 class-4 rows

# --- Value fields (LOCKED) ---
VALUE_FIELD_MARKET = "curmkttot"   # distribution / comparison basis
VALUE_FIELD_TAXABLE = "curtxbtot"  # tax-bill SIGNAL basis (transitional taxable)
VALUE_FIELD_TRANSITIONAL = "curtrntot"  # phase-in gap numerator
VALUE_FIELD_ACTUAL = "curacttot"        # mechanical 0.45 x market; phase-in gap denominator

# --- Roll column names (locked from live introspection) ---
COL_TAX_CLASS = "curtaxclass"
COL_BBL = "parid"
COL_BLDG_CLASS = "bldg_class"
COL_ZIP = "zip_code"
COL_YEAR_BUILT = "yrbuilt"      # display-only; failed 80% fill gate (68.1%)
COL_GROSS_SQFT = "gross_sqft"   # gross-building-area fallback when PLUTO join misses

# --- Rates (CONTEXT only) ---
CLASS4_ASSESSMENT_RATIO = 0.45
FY2026_CLASS4_TAX_RATE = 0.10848

# --- Gates (LOCKED, tunable in Phase 4) ---
MIN_COMP_COUNT = 8          # below this -> visible refusal
COMP_SF_BAND = 0.50         # +/-50% of target SF
