"""Comp-selection invariants for the office / distance / radius-first model.

Skipped if the DuckDB isn't built. Selection contract only — no statistics.
"""
import duckdb
import pytest

from screener import config
from screener.comps import select_comps
from screener.jurisdiction import CompCriteria, get_jurisdiction

pytestmark = pytest.mark.skipif(
    not config.DB_PATH.exists(), reason="screener.duckdb not built; run loader + pluto first"
)

OFFICE_DENSE = "1000090001"     # O4 Manhattan — succeeds at 0.5 mi (~28 comps)
OFFICE_EXPAND = "1000100015"    # O6 Manhattan — succeeds via expansion (~0.6 mi)
OFFICE_ISOLATED = "1000580001"  # O4 ~8.97M SF — no in-band peers, refuses
NON_OFFICE = "3000250001"       # K4 store — out of scope for v1


@pytest.fixture(scope="module")
def setup():
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    crit = CompCriteria.load()
    juris = get_jurisdiction(crit.jurisdiction)
    yield con, juris, crit
    con.close()


def test_config_loads_office_distance_model():
    c = CompCriteria.load()
    assert c.sf_band == 0.50
    assert c.activated_products == ["O"]
    assert c.radius_start_miles == 0.25 and c.radius_cap_miles == 1.0   # start lowered 0.5->0.25
    assert c.office_buckets["O5"] == c.office_buckets["O6"]      # grouped
    assert c.office_buckets["O7"] == c.office_buckets["O9"]      # grouped
    assert c.office_buckets["O1"] != c.office_buckets["O2"]      # exact


def test_non_office_subject_is_out_of_scope(setup):
    con, juris, crit = setup
    cs = select_comps(con, NON_OFFICE, juris, crit)
    assert cs.refused and cs.note == "out_of_scope_v1" and cs.count == 0


def test_subject_not_found(setup):
    con, juris, crit = setup
    cs = select_comps(con, "9999999999", juris, crit)
    assert cs.note == "subject_not_found"


def test_dense_office_succeeds_within_start_radius(setup):
    con, juris, crit = setup
    cs = select_comps(con, OFFICE_DENSE, juris, crit)
    assert not cs.refused
    assert cs.count >= crit.min_comp_count
    assert cs.radius_used_miles <= crit.radius_start_miles


def test_expansion_radius_between_start_and_cap(setup):
    con, juris, crit = setup
    cs = select_comps(con, OFFICE_EXPAND, juris, crit)
    assert not cs.refused
    assert crit.radius_start_miles < cs.radius_used_miles <= crit.radius_cap_miles


def test_isolated_office_refuses_with_radius_cap(setup):
    con, juris, crit = setup
    cs = select_comps(con, OFFICE_ISOLATED, juris, crit)
    assert cs.refused and cs.note == "insufficient_comps_within_cap"
    assert cs.radius_used_miles == crit.radius_cap_miles


def test_all_comps_within_radius_and_sorted(setup):
    con, juris, crit = setup
    cs = select_comps(con, OFFICE_DENSE, juris, crit)
    dists = [c.distance_miles for c in cs.comps]
    assert dists == sorted(dists)
    assert all(d <= cs.radius_used_miles + 1e-9 for d in dists)


def test_all_comps_share_bucket_and_sf_band(setup):
    con, juris, crit = setup
    cs = select_comps(con, OFFICE_DENSE, juris, crit)
    subj_bucket = cs.subject["bucket"]
    sf = cs.subject["sf"]
    lo, hi = sf * (1 - crit.sf_band), sf * (1 + crit.sf_band)
    assert all(c.bucket == subj_bucket for c in cs.comps)
    assert all(lo <= c.sf <= hi for c in cs.comps)


def test_comps_exclude_subject_and_condos(setup):
    con, juris, crit = setup
    cs = select_comps(con, OFFICE_DENSE, juris, crit)
    for c in cs.comps:
        assert c.citation.parcel_id != OFFICE_DENSE
        assert not (c.bldg_class or "").startswith("R")
        assert int(c.citation.parcel_id[6:10]) < crit.condo_unit_lot_min


def test_every_comp_carries_provenance_and_sf_version(setup):
    con, juris, crit = setup
    cs = select_comps(con, OFFICE_DENSE, juris, crit)
    assert cs.count > 0
    for c in cs.comps:
        assert c.citation.source_dataset and c.citation.roll_year
        assert c.citation.parcel_id and c.citation.retrieval_date
        # SF value cites its source per the $/SF output contract.
        if c.sf_source == "pluto_bldgarea":
            assert c.sf_dataset_version and "64uk-42ks" in c.sf_dataset_version


def test_o5_and_o6_cross_match(setup):
    con, juris, crit = setup
    # An O5 or O6 subject's comps may include both O5 and O6 (grouped bucket).
    cs = select_comps(con, OFFICE_EXPAND, juris, crit)  # O6 subject
    classes = {c.bldg_class for c in cs.comps}
    assert classes.issubset({"O5", "O6"})


# --- tiered class fallback -------------------------------------------------
O1_FALLBACK = "2023070046"   # Bronx O1 — exact insufficient, falls back to O2
O1_MIXED = "2038300044"      # Bronx O1 — exact O1 + adjacent O2 in the result


def test_fully_exact_set_reports_no_fallback(setup):
    con, juris, crit = setup
    cs = select_comps(con, OFFICE_DENSE, juris, crit)  # O4, dense, all exact
    assert not cs.fallback_triggered
    assert cs.exact_count == cs.count and cs.adjacent_count == 0
    assert all(c.match_type == "exact" for c in cs.comps)
    assert "all" in cs.composition_label()


def test_fallback_tags_exact_vs_adjacent(setup):
    con, juris, crit = setup
    cs = select_comps(con, O1_FALLBACK, juris, crit)
    assert not cs.refused and cs.fallback_triggered
    # exact comps share the subject's class; adjacent are ladder classes.
    assert all(c.bldg_class == "O1" for c in cs.comps if c.match_type == "exact")
    assert all(c.bldg_class in ("O2", "O3") for c in cs.comps if c.match_type == "adjacent")
    assert cs.exact_count + cs.adjacent_count == cs.count
    assert sum(cs.adjacent_breakdown.values()) == cs.adjacent_count


def test_exact_comps_within_radius_and_counted(setup):
    con, juris, crit = setup
    cs = select_comps(con, O1_MIXED, juris, crit)
    exact = [c for c in cs.comps if c.match_type == "exact"]
    assert all(c.bldg_class == "O1" for c in exact)
    assert all(c.distance_miles <= cs.radius_used_miles + 1e-9 for c in exact)
    assert len(exact) == cs.exact_count


def test_o4_has_no_fallback(setup):
    con, juris, crit = setup
    # O4 ladder is empty: any O4 result is fully exact, and an isolated O4 refuses
    # rather than borrowing another class.
    cs = select_comps(con, OFFICE_DENSE, juris, crit)
    assert not cs.fallback_triggered and all(c.bldg_class == "O4" for c in cs.comps)
    iso = select_comps(con, OFFICE_ISOLATED, juris, crit)
    assert iso.refused and iso.note == "insufficient_comps_within_cap"


def test_composition_label_shape(setup):
    con, juris, crit = setup
    cs = select_comps(con, O1_FALLBACK, juris, crit)
    label = cs.composition_label()
    assert "exact" in label and "adjacent" in label and "radius" in label


# --- non-positive market value (tax-exempt) exclusion --------------------------
TAX_EXEMPT_SUBJECT = "1000380001"  # O4 Manhattan, curmkttot = 0


def test_tax_exempt_subject_refuses(setup):
    con, juris, crit = setup
    cs = select_comps(con, TAX_EXEMPT_SUBJECT, juris, crit)
    assert cs.refused and cs.note == "subject_tax_exempt"


def test_no_exempt_comps_in_set(setup):
    con, juris, crit = setup
    cs = select_comps(con, OFFICE_DENSE, juris, crit)
    assert all(c.curmkttot is not None and c.curmkttot > 0 for c in cs.comps)


def test_radius_override_fixed_does_not_autowiden(setup):
    con, juris, crit = setup
    tight = crit.model_copy(update={"radius_start_miles": 0.1, "radius_cap_miles": 0.1})
    cs = select_comps(con, OFFICE_DENSE, juris, tight)
    if cs.refused:
        assert cs.note == "insufficient_comps_within_cap" and cs.radius_used_miles == 0.1
    else:
        assert cs.radius_used_miles <= 0.1 + 1e-9   # fixed radius, never widens out to 1.0


def test_radius_widen_returns_at_least_as_many(setup):
    con, juris, crit = setup
    base = select_comps(con, OFFICE_DENSE, juris, crit).count
    wide = crit.model_copy(update={"radius_start_miles": 2.0, "radius_cap_miles": 2.0})
    assert select_comps(con, OFFICE_DENSE, juris, wide).count >= base


def test_radius_used_matches_applied(setup):
    con, juris, crit = setup
    fixed = crit.model_copy(update={"radius_start_miles": 0.5, "radius_cap_miles": 0.5})
    cs = select_comps(con, OFFICE_DENSE, juris, fixed)
    if not cs.refused:
        assert cs.radius_used_miles == 0.5


def test_exclusions_table_has_non_positive_reason(setup):
    con, juris, crit = setup
    if con.execute("SELECT count(*) FROM information_schema.tables "
                   "WHERE table_name='exclusions'").fetchone()[0] != 1:
        pytest.skip("exclusions not built")
    n = con.execute(
        "SELECT count(*) FROM exclusions WHERE reason_code='NON_POSITIVE_MARKET_VALUE'"
    ).fetchone()[0]
    assert n > 0
