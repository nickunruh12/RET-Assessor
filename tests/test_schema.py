"""The citation contract is the load-bearing invariant. Test it hard.

If any of these pass when they should fail, an un-cited number could reach a user.
"""
from datetime import date

import pytest
from pydantic import BaseModel, ValidationError

from screener.schema import Citation, CitedRow


def _valid_kwargs():
    return dict(
        source_dataset="8y4t-faws",
        dataset_version="FY2027 final roll",
        roll_year="2027",
        retrieval_date=date(2026, 6, 19),
        parcel_id="1002230035",
    )


def test_full_tuple_constructs():
    c = Citation(**_valid_kwargs())
    assert c.parcel_id == "1002230035"
    assert c.roll_year == "2027"


@pytest.mark.parametrize(
    "missing",
    ["source_dataset", "dataset_version", "roll_year", "retrieval_date", "parcel_id"],
)
def test_missing_any_field_is_unconstructible(missing):
    kwargs = _valid_kwargs()
    del kwargs[missing]
    with pytest.raises(ValidationError):
        Citation(**kwargs)


@pytest.mark.parametrize(
    "blank_field", ["source_dataset", "dataset_version", "roll_year", "parcel_id"]
)
@pytest.mark.parametrize("blank_value", ["", "   "])
def test_blank_strings_rejected(blank_field, blank_value):
    kwargs = _valid_kwargs()
    kwargs[blank_field] = blank_value
    with pytest.raises(ValidationError):
        Citation(**kwargs)


def test_citation_is_frozen():
    c = Citation(**_valid_kwargs())
    with pytest.raises(ValidationError):
        c.parcel_id = "9999999999"


def test_strings_are_stripped():
    kwargs = _valid_kwargs()
    kwargs["parcel_id"] = "  1002230035  "
    assert Citation(**kwargs).parcel_id == "1002230035"


def test_cited_row_requires_citation():
    with pytest.raises(ValidationError):
        CitedRow()  # no citation -> not constructible


def test_derived_row_subclass_requires_citation():
    class ParcelRow(CitedRow):
        market_value: int

    # Missing citation: not constructible even with valid data fields.
    with pytest.raises(ValidationError):
        ParcelRow(market_value=1_700_000)

    row = ParcelRow(citation=Citation(**_valid_kwargs()), market_value=1_700_000)
    assert row.citation.parcel_id == "1002230035"
    assert row.market_value == 1_700_000


def test_extra_fields_forbidden_on_citation():
    kwargs = _valid_kwargs()
    kwargs["sneaky"] = "value"
    with pytest.raises(ValidationError):
        Citation(**kwargs)
