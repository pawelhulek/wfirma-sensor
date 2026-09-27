"""Cost invoices (wFirma "expenses"): parsing and the bills-to-pay summary."""

from datetime import date
from decimal import Decimal

from custom_components.wfirma.expenses import Expense, summarize_expenses

from .builders import expense_dict

TODAY = date(2026, 9, 27)


def exp(**kw) -> Expense:
    return Expense.from_api(expense_dict(**kw))


def test_parsing() -> None:
    e = exp()
    assert e.number == "FZ 12/09/2026"
    assert e.contractor == "Orange Polska S.A."
    assert e.due_date == date(2026, 10, 5)
    assert (e.gross, e.remaining) == (Decimal("123.00"), Decimal("123.00"))
    assert e.is_unpaid


def test_drafts_and_rejected_documents_are_not_bills() -> None:
    assert not exp(draft="1").is_unpaid
    assert not exp(is_rejected="1").is_unpaid
    assert not exp(remaining="0.00").is_unpaid


def test_summary_orders_by_due_date_and_splits_currencies() -> None:
    summary = summarize_expenses(
        (
            exp(id="1", fullnumber="late", payment_date="2026-09-20", remaining="100.00"),
            exp(id="2", fullnumber="soon", payment_date="2026-10-01", remaining="50.00"),
            exp(id="3", fullnumber="eur", payment_date="2026-10-02", remaining="10.00", currency="eur"),
            exp(id="4", fullnumber="draft", draft="1"),
        ),
        TODAY,
    )
    assert [e.number for e in summary.unpaid] == ["late", "soon", "eur"]
    assert summary.unpaid_count == 3
    assert summary.unpaid_amount == Decimal("150.00")
    assert dict(summary.other_currencies) == {"EUR": Decimal("10.00")}
    assert [e.number for e in summary.overdue] == ["late"]
    assert summary.next_due == date(2026, 9, 20)
    assert summary.unpaid_attributes()[0] == {
        "number": "late",
        "contractor": "Orange Polska S.A.",
        "remaining": 100.0,
        "currency": "PLN",
        "due_date": "2026-09-20",
    }


def test_empty_summary() -> None:
    summary = summarize_expenses((), TODAY)
    assert (summary.unpaid_count, summary.unpaid_amount, summary.next_due) == (0, Decimal("0"), None)
