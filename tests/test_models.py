"""Invoice parsing and classification."""

from datetime import date
from decimal import Decimal

import pytest

from custom_components.wfirma.models import Company, Invoice

from .builders import invoice_dict


def test_parses_numbers_dates_and_contractor() -> None:
    inv = Invoice.from_api(invoice_dict())

    assert inv.id == "101"
    assert inv.number == "FV 1/9/2026"
    assert inv.issue_date == date(2026, 9, 10)
    assert inv.due_date == date(2026, 9, 24)
    assert inv.gross == Decimal("1230.00")
    assert inv.net == Decimal("1000.00")
    assert inv.remaining == Decimal("1230.00")
    assert inv.currency == "PLN"
    assert inv.doc_type == "normal"
    assert inv.payment_state == "unpaid"
    assert inv.contractor == "ACME Sp. z o.o."


def test_invoice_is_immutable() -> None:
    inv = Invoice.from_api(invoice_dict())
    with pytest.raises(AttributeError):
        inv.remaining = Decimal("0")  # type: ignore[misc]


@pytest.mark.parametrize("value", [None, "", "0000-00-00", "not-a-date"])
def test_missing_or_bad_due_date_is_none(value: object) -> None:
    assert Invoice.from_api(invoice_dict(paymentdate=value)).due_date is None


@pytest.mark.parametrize("value", [None, "", "abc"])
def test_missing_or_bad_amount_is_zero(value: object) -> None:
    assert Invoice.from_api(invoice_dict(remaining=value)).remaining == Decimal("0")


def test_defaults_when_optional_fields_absent() -> None:
    raw = invoice_dict()
    for key in ("currency", "contractor_detail", "fullnumber", "type", "paymentstate"):
        raw.pop(key)
    inv = Invoice.from_api(raw)
    assert inv.currency == "PLN"
    assert inv.contractor == ""
    assert inv.number == "101"
    assert inv.doc_type == "normal"
    assert inv.payment_state == "undefined"


def test_contractor_falls_back_to_altname() -> None:
    raw = invoice_dict(contractor_detail={"name": "", "altname": "ACME"})
    assert Invoice.from_api(raw).contractor == "ACME"


@pytest.mark.parametrize(
    ("doc_type", "is_sales"),
    [
        ("normal", True),
        ("bill", True),
        ("correction", True),
        ("receipt_normal", True),
        ("receipt_fiscal_bill", True),
        ("income_normal", True),
        ("proforma", False),
        ("proforma_bill", False),
        ("offer", False),
        ("offer_bill", False),
        ("normal_draft", False),
    ],
)
def test_only_sales_documents_count(doc_type: str, is_sales: bool) -> None:
    assert Invoice.from_api(invoice_dict(type=doc_type)).is_sales is is_sales


def test_unpaid_needs_a_balance_and_a_sales_document() -> None:
    assert Invoice.from_api(invoice_dict()).is_unpaid
    assert not Invoice.from_api(invoice_dict(remaining="0.00")).is_unpaid
    assert not Invoice.from_api(invoice_dict(type="proforma")).is_unpaid


def test_overdue_only_after_the_payment_date() -> None:
    inv = Invoice.from_api(invoice_dict(paymentdate="2026-09-24"))
    assert not inv.is_overdue(date(2026, 9, 24))
    assert inv.is_overdue(date(2026, 9, 25))
    assert not Invoice.from_api(invoice_dict(paymentdate="")).is_overdue(date(2030, 1, 1))
    assert not Invoice.from_api(invoice_dict(remaining="0")).is_overdue(date(2030, 1, 1))


def test_attribute_view_is_json_friendly() -> None:
    attrs = Invoice.from_api(invoice_dict()).as_attribute()
    assert attrs == {
        "number": "FV 1/9/2026",
        "contractor": "ACME Sp. z o.o.",
        "remaining": 1230.0,
        "currency": "PLN",
        "due_date": "2026-09-24",
    }


def test_company_from_api_prefers_company_fields() -> None:
    raw = {"id": "9", "company_id": "4242", "company_name": "Hulek IT", "name": "relation"}
    assert Company.from_api(raw) == Company(id="4242", name="Hulek IT")


def test_company_from_api_plain_fields() -> None:
    assert Company.from_api({"id": "77", "name": "Solo"}) == Company(id="77", name="Solo")
    assert Company.from_api({"name": "no id"}) is None
