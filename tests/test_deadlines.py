"""ZUS, income tax and VAT deadlines, and matching ZUS payments to them."""

from datetime import date
from decimal import Decimal

import pytest

from custom_components.wfirma.deadlines import (
    Deadline,
    DeadlineKind,
    TaxPayment,
    TaxProfile,
    build_deadlines,
    next_deadline,
    statutory_due,
)

from .builders import payment_dict

LUMP_VAT = TaxProfile(income_tax="lumpregister", vat_payer=True)
TODAY = date(2026, 9, 27)


def zus(paid_on: str, amount: str = "1900.00") -> TaxPayment:
    payment = TaxPayment.from_api(payment_dict(date=paid_on, value=amount, social="1400.00", health="500.00"))
    assert payment is not None
    return payment


def tax(paid_on: str) -> TaxPayment:
    payment = TaxPayment.from_api(payment_dict(date=paid_on, value="800.00"))
    assert payment is not None
    return payment


@pytest.mark.parametrize(
    ("kind", "period", "expected"),
    [
        (DeadlineKind.ZUS, date(2026, 8, 1), date(2026, 9, 21)),  # 20 Sep is a Sunday
        (DeadlineKind.ZUS, date(2026, 9, 1), date(2026, 10, 20)),
        (DeadlineKind.INCOME_TAX, date(2026, 12, 1), date(2027, 1, 20)),  # December: the early, safe date
        (DeadlineKind.VAT, date(2026, 9, 1), date(2026, 10, 26)),  # 25 Oct is a Sunday
        (DeadlineKind.VAT, date(2026, 11, 1), date(2026, 12, 28)),  # 25-27 Dec are days off
    ],
)
def test_statutory_due(kind: DeadlineKind, period: date, expected: date) -> None:
    assert statutory_due(kind, period, LUMP_VAT) == expected


def test_tax_card_is_due_on_the_7th_and_december_in_december() -> None:
    card = TaxProfile(income_tax="card", vat_payer=False)
    assert statutory_due(DeadlineKind.INCOME_TAX, date(2026, 9, 1), card) == date(2026, 10, 7)
    assert statutory_due(DeadlineKind.INCOME_TAX, date(2026, 12, 1), card) == date(2026, 12, 28)


def test_profile_decides_which_deadlines_exist() -> None:
    kinds = {d.kind for d in build_deadlines(LUMP_VAT, (), TODAY)}
    assert kinds == {DeadlineKind.ZUS, DeadlineKind.INCOME_TAX, DeadlineKind.VAT}
    no_vat_unknown_tax = TaxProfile(income_tax="something-new", vat_payer=False)
    assert {d.kind for d in build_deadlines(no_vat_unknown_tax, (), TODAY)} == {DeadlineKind.ZUS}


def test_window_runs_from_two_months_back_to_a_year_ahead() -> None:
    dues = [d.due for d in build_deadlines(LUMP_VAT, (), TODAY) if d.kind is DeadlineKind.ZUS]
    assert min(dues) >= date(2026, 7, 27)
    assert max(dues) <= date(2027, 9, 27)
    assert dues == sorted(dues)


def test_zus_paid_in_the_due_month_settles_the_previous_month() -> None:
    deadlines = build_deadlines(LUMP_VAT, (zus("2026-08-13"),), TODAY)
    by_period = {d.period: d for d in deadlines if d.kind is DeadlineKind.ZUS}
    assert by_period[date(2026, 7, 1)].paid is True
    assert by_period[date(2026, 8, 1)].paid is False
    assert by_period[date(2026, 8, 1)].is_overdue(TODAY)
    assert by_period[date(2026, 9, 1)].paid is False
    assert not by_period[date(2026, 9, 1)].is_overdue(TODAY)


def test_without_any_zus_history_the_status_is_unknown() -> None:
    zus_deadlines = [d for d in build_deadlines(LUMP_VAT, (tax("2026-09-15"),), TODAY) if d.kind is DeadlineKind.ZUS]
    assert {d.paid for d in zus_deadlines} == {None}
    assert not any(d.is_overdue(TODAY) for d in zus_deadlines)


def test_tax_payments_cannot_be_told_apart_so_tax_status_is_unknown() -> None:
    deadlines = build_deadlines(LUMP_VAT, (tax("2026-09-15"), zus("2026-09-10")), TODAY)
    assert {d.paid for d in deadlines if d.kind is not DeadlineKind.ZUS} == {None}


def test_next_zus_is_the_oldest_unpaid_even_when_overdue() -> None:
    deadlines = build_deadlines(LUMP_VAT, (zus("2026-08-13"),), TODAY)
    nxt = next_deadline(deadlines, DeadlineKind.ZUS, TODAY)
    assert nxt is not None
    assert (nxt.period, nxt.due, nxt.days_left(TODAY)) == (date(2026, 8, 1), date(2026, 9, 21), -6)


def test_next_zus_moves_on_once_paid() -> None:
    deadlines = build_deadlines(LUMP_VAT, (zus("2026-08-13"), zus("2026-09-18")), TODAY)
    nxt = next_deadline(deadlines, DeadlineKind.ZUS, TODAY)
    assert nxt is not None and nxt.due == date(2026, 10, 20)


def test_next_tax_deadline_is_the_first_one_not_yet_past() -> None:
    deadlines = build_deadlines(LUMP_VAT, (), TODAY)
    vat = next_deadline(deadlines, DeadlineKind.VAT, TODAY)
    income = next_deadline(deadlines, DeadlineKind.INCOME_TAX, TODAY)
    assert vat is not None and vat.due == date(2026, 10, 26)
    assert income is not None and income.due == date(2026, 10, 20)


def test_next_deadline_is_none_for_a_kind_that_does_not_apply() -> None:
    no_vat = TaxProfile(income_tax="lumpregister", vat_payer=False)
    assert next_deadline(build_deadlines(no_vat, (), TODAY), DeadlineKind.VAT, TODAY) is None


def test_payment_parsing() -> None:
    payment = zus("2026-08-13", "1926.76")
    assert (payment.paid_on, payment.amount, payment.is_zus) == (date(2026, 8, 13), Decimal("1926.76"), True)
    assert tax("2026-09-15").is_zus is False
    assert TaxPayment.from_api(payment_dict(date="0000-00-00")) is None


def test_profile_from_api() -> None:
    assert TaxProfile.from_api({"tax": "lumpregister", "vat_payer": "1"}) == LUMP_VAT
    assert TaxProfile.from_api({"tax": None, "vat_payer": "0"}) == TaxProfile(income_tax="", vat_payer=False)


def test_deadline_is_immutable() -> None:
    deadline = Deadline(DeadlineKind.ZUS, date(2026, 8, 1), date(2026, 9, 21), None)
    with pytest.raises(AttributeError):
        deadline.paid = True  # type: ignore[misc]
