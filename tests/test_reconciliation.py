"""Subject-panel identity line is built ONLY from the resolved parcel's PUBLISHED fields;
a user-typed ZIP/borough is never echoed as the address. A reconciliation note surfaces
(descriptively, no refusal) when a typed ZIP/borough conflicts with the published value.
"""
from screener.geocode import ResolveResult
from screener.serialize import _reconciliation_note, _subject_panel, _zip5


def _resolve(zip_code=None, borough=None):
    # a user-typed search that resolved to a BBL; geocoder returns only bbl, so these
    # zip/borough fields are the VERBATIM user input.
    return ResolveResult(ok=True, bbl="1000460003", house_number="100", street="Broadway",
                         borough=borough, zip_code=zip_code, bldg_class="O4",
                         refused=False, reason=None, message=None)


def _subject(zip_code="10005", borough="Manhattan"):
    return {"parcel_id": "1000460003", "house_number": "100", "street_name": "BROADWAY",
            "zip_code": zip_code, "borough": borough, "bldg_class": "O4",
            "bucket_label": "Office", "curmkttot": 5_000_000, "curtxbtot": 2_000_000,
            "sf": 50_000, "sf_source": "pluto_bldgarea", "year_built": "1900"}


# --- step 2: address line uses ONLY published fields, never the typed ZIP -------------
def test_address_never_echoes_typed_zip():
    panel = _subject_panel(_subject(zip_code="10005"), _resolve(zip_code="10014"), rate=0.10848)
    assert "10014" not in (panel["address"] or "")        # typed ZIP not in identity line
    assert panel["address"] == "100 BROADWAY, Manhattan"  # published house/street/borough
    assert panel["zip_code"] == "10005"                   # Borough/ZIP row = published


def test_panel_zip_is_single_published_value():
    # the only ZIP anywhere in the panel is the published one
    panel = _subject_panel(_subject(zip_code="10005"), _resolve(zip_code="10014"), rate=0.10848)
    assert _zip5(panel["zip_code"]) == "10005"
    assert "10014" not in (panel["address"] or "")


def test_address_falls_back_to_published_zip_when_no_borough():
    subj = _subject(zip_code="10005", borough=None)
    panel = _subject_panel(subj, _resolve(zip_code="10014"), rate=0.10848)
    assert panel["address"] == "100 BROADWAY, ZIP 10005"   # published ZIP, not typed 10014


# --- step 3: reconciliation note only on conflict, descriptive, no refusal -------------
def test_note_appears_on_zip_conflict_naming_both():
    note = _reconciliation_note(_resolve(zip_code="10014"), _subject(zip_code="10005"))
    assert note == ("You searched ZIP 10014. The matching parcel's published ZIP is 10005. "
                    "Confirm this is the correct building.")


def test_no_note_on_matching_zip():
    assert _reconciliation_note(_resolve(zip_code="10005"), _subject(zip_code="10005")) is None


def test_no_note_when_zip_omitted():
    assert _reconciliation_note(_resolve(zip_code=None), _subject(zip_code="10005")) is None


def test_no_note_on_bbl_only_run():
    assert _reconciliation_note(None, _subject(zip_code="10005")) is None


def test_note_on_borough_conflict():
    note = _reconciliation_note(_resolve(borough="Brooklyn"), _subject(borough="Manhattan"))
    assert "published borough is Manhattan" in note and "searched borough Brooklyn" in note


def test_zip5_normalizes_plus_four():
    assert _zip5("10005-1234") == "10005"
    assert _zip5(" 10005 ") == "10005"
    # ZIP+4 vs 5-digit of the same ZIP is NOT a conflict
    assert _reconciliation_note(_resolve(zip_code="10005-1234"), _subject(zip_code="10005")) is None


def test_note_has_no_refusal_language():
    note = _reconciliation_note(_resolve(zip_code="10014"), _subject(zip_code="10005"))
    for banned in ("refuse", "cannot", "error", "invalid", "rejected"):
        assert banned not in note.lower()
