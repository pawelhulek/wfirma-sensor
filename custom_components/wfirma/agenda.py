"""What the calendar shows: tax deadlines and payment dates, as plain all-day items."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from .coordinator import Snapshot
from .deadlines import Deadline, DeadlineKind, last_payment

_TEXT: Mapping[str, Mapping[str, str]] = {
    "pl": {
        "zus": "ZUS za {period}",
        "lumpregister": "Ryczałt za {period}",
        "linear": "Zaliczka PIT za {period}",
        "scale": "Zaliczka PIT za {period}",
        "card": "Karta podatkowa za {period}",
        "vat": "VAT (JPK_V7M) za {period}",
        "receivable": "Wpłata: {number} ({contractor})",
        "payable": "Zapłać: {number} ({contractor})",
        "amount": "Kwota: {amount} {currency}",
        "estimate": "Szacunkowo {amount} PLN (ostatnia wpłata {on})",
        "paid": "Opłacone (według wFirmy).",
        "unpaid": "W wFirmie nie ma jeszcze tej wpłaty.",
        "unknown": "wFirma nie pokazuje, czy to już opłacone.",
    },
    "en": {
        "zus": "ZUS for {period}",
        "lumpregister": "Lump-sum tax for {period}",
        "linear": "PIT advance for {period}",
        "scale": "PIT advance for {period}",
        "card": "Tax card for {period}",
        "vat": "VAT (JPK_V7M) for {period}",
        "receivable": "Payment due: {number} ({contractor})",
        "payable": "Pay: {number} ({contractor})",
        "amount": "Amount: {amount} {currency}",
        "estimate": "About {amount} PLN (last payment {on})",
        "paid": "Paid (according to wFirma).",
        "unpaid": "wFirma has no record of this payment yet.",
        "unknown": "wFirma does not show whether this is paid.",
    },
}
_PAID_MARK = "✅ "


@dataclass(frozen=True, slots=True)
class AgendaItem:
    day: date
    summary: str
    description: str
    uid: str


def _texts(language: str) -> Mapping[str, str]:
    return _TEXT.get(language.split("-")[0].lower(), _TEXT["en"])


def _period(deadline: Deadline, language: str) -> str:
    separator = "." if language.startswith("pl") else "/"
    return f"{deadline.period.month:02d}{separator}{deadline.period.year}"


def _deadline_item(deadline: Deadline, snapshot: Snapshot, t: Mapping[str, str], language: str) -> AgendaItem:
    if deadline.kind is DeadlineKind.INCOME_TAX and snapshot.profile is not None:
        key = snapshot.profile.income_tax
    else:
        key = deadline.kind.value
    title = t[key].format(period=_period(deadline, language))
    status = {True: t["paid"], False: t["unpaid"], None: t["unknown"]}[deadline.paid]
    lines = [status]
    if deadline.kind is DeadlineKind.ZUS and (last := last_payment(snapshot.tax_payments or (), zus=True)):
        lines.insert(0, t["estimate"].format(amount=f"{last.amount:.2f}", on=last.paid_on.isoformat()))
    return AgendaItem(
        day=deadline.due,
        summary=(_PAID_MARK if deadline.paid else "") + title,
        description="\n".join(lines),
        uid=f"{deadline.kind.value}-{deadline.period.isoformat()}",
    )


def agenda(snapshot: Snapshot, language: str) -> tuple[AgendaItem, ...]:
    """Every dated item, soonest first."""
    t = _texts(language)
    items = [_deadline_item(d, snapshot, t, language) for d in snapshot.deadlines or ()]
    for inv in snapshot.invoices.unpaid:
        if inv.due_date is not None:
            summary = t["receivable"].format(number=inv.number, contractor=inv.contractor)
            amount = t["amount"].format(amount=f"{inv.remaining:.2f}", currency=inv.currency)
            items.append(AgendaItem(inv.due_date, summary, amount, f"invoice-{inv.id}"))
    for exp in snapshot.expenses.unpaid if snapshot.expenses else ():
        if exp.due_date is not None:
            summary = t["payable"].format(number=exp.number, contractor=exp.contractor)
            amount = t["amount"].format(amount=f"{exp.remaining:.2f}", currency=exp.currency)
            items.append(AgendaItem(exp.due_date, summary, amount, f"expense-{exp.id}"))
    return tuple(sorted(items, key=lambda i: (i.day, i.summary)))
