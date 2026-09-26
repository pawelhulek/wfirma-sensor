"""Turning invoices into sensor values."""

from datetime import date
from decimal import Decimal

from custom_components.wfirma.models import Invoice
from custom_components.wfirma.summary import settled_since, summarize

from .builders import invoice_dict

TODAY = date(2026, 9, 25)


def inv(**kw) -> Invoice:
    return Invoice.from_api(invoice_dict(**kw))


def test_empty_account() -> None:
    s = summarize((), (), TODAY)
    assert (s.unpaid_count, s.unpaid_amount, s.overdue_count, s.overdue_amount) == (0, 0, 0, 0)
    assert (s.revenue_net, s.revenue_gross, s.revenue_count) == (0, 0, 0)
    assert s.unpaid_ids == frozenset()


def test_unpaid_and_overdue_totals_in_base_currency() -> None:
    unpaid = (
        inv(id="1", remaining="100.00", paymentdate="2026-09-30"),  # not yet due
        inv(id="2", remaining="250.50", paymentdate="2026-09-01"),  # overdue
        inv(id="3", remaining="49.50", paymentdate="2026-08-15"),   # overdue, oldest
    )
    s = summarize(unpaid, (), TODAY)
    assert s.unpaid_count == 3
    assert s.unpaid_amount == Decimal("400.00")
    assert s.overdue_count == 2
    assert s.overdue_amount == Decimal("300.00")
    assert [i.id for i in s.overdue] == ["3", "2"]  # oldest due first


def test_other_currencies_are_counted_but_not_added_to_pln() -> None:
    unpaid = (
        inv(id="1", remaining="100.00", paymentdate="2026-09-30"),
        inv(id="2", remaining="80.00", currency="EUR", paymentdate="2026-09-01"),
        inv(id="3", remaining="20.00", currency="EUR", paymentdate="2026-09-30"),
    )
    s = summarize(unpaid, (), TODAY)
    assert s.unpaid_count == 3
    assert s.unpaid_amount == Decimal("100.00")
    assert dict(s.unpaid_other_currencies) == {"EUR": Decimal("100.00")}
    assert s.overdue_count == 1
    assert s.overdue_amount == Decimal("0")
    assert dict(s.overdue_other_currencies) == {"EUR": Decimal("80.00")}


def test_ignores_proformas_and_settled_documents_even_if_api_returned_them() -> None:
    unpaid = (
        inv(id="1", remaining="100.00"),
        inv(id="2", remaining="999.00", type="proforma"),
        inv(id="3", remaining="0.00"),
    )
    s = summarize(unpaid, (), TODAY)
    assert s.unpaid_count == 1
    assert s.unpaid_ids == frozenset({"1"})


def test_revenue_this_month_counts_sales_including_corrections() -> None:
    issued = (
        inv(id="1", netto="1000.00", total="1230.00", date="2026-09-02"),
        inv(id="2", netto="-100.00", total="-123.00", date="2026-09-05", type="correction"),
        inv(id="3", netto="500.00", total="615.00", date="2026-09-06", type="proforma"),
        inv(id="4", netto="200.00", total="246.00", date="2026-08-31"),  # last month
        inv(id="5", netto="50.00", total="50.00", date="2026-09-07", currency="EUR"),
    )
    s = summarize((), issued, TODAY)
    assert s.revenue_net == Decimal("900.00")
    assert s.revenue_gross == Decimal("1107.00")
    assert s.revenue_count == 2
    assert dict(s.revenue_other_currencies) == {"EUR": Decimal("50.00")}


def test_summary_is_immutable() -> None:
    s = summarize((inv(id="1"),), (), TODAY)
    try:
        s.unpaid_other_currencies["EUR"] = Decimal("1")  # type: ignore[index]
    except TypeError:
        pass
    else:
        raise AssertionError("mapping must be read-only")


def test_attribute_lists_are_capped() -> None:
    unpaid = tuple(inv(id=str(i), paymentdate=f"2026-08-{i + 1:02d}") for i in range(25))
    s = summarize(unpaid, (), TODAY)
    assert s.unpaid_count == 25
    assert len(s.unpaid_attributes()) == 10
    assert s.unpaid_attributes()[0]["due_date"] == "2026-08-01"


def test_settled_since_reports_invoices_that_left_the_unpaid_set() -> None:
    now = summarize((inv(id="2"), inv(id="3")), (), TODAY)
    assert settled_since(frozenset({"1", "2"}), now) == frozenset({"1"})
    assert settled_since(frozenset(), now) == frozenset()
