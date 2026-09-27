"""Builders for wFirma API payloads used across the tests."""

from typing import Any


def invoice_dict(**overrides: Any) -> dict[str, Any]:
    """An invoice record as wFirma returns it in JSON (numbers arrive as strings)."""
    base: dict[str, Any] = {
        "id": "101",
        "fullnumber": "FV 1/9/2026",
        "date": "2026-09-10",
        "paymentdate": "2026-09-24",
        "paymentstate": "unpaid",
        "total": "1230.00",
        "netto": "1000.00",
        "tax": "230.00",
        "remaining": "1230.00",
        "alreadypaid": "0.00",
        "currency": "PLN",
        "type": "normal",
        "contractor_detail": {"name": "ACME Sp. z o.o.", "nip": "1234567890"},
    }
    return {**base, **overrides}


def expense_dict(**overrides: Any) -> dict[str, Any]:
    """A cost invoice ("expense") record, trimmed to the fields the integration reads."""
    base: dict[str, Any] = {
        "id": "501",
        "fullnumber": "FZ 12/09/2026",
        "date": "2026-09-21",
        "payment_date": "2026-10-05",
        "paymentstate": "unpaid",
        "brutto": "123.00",
        "netto": "100.00",
        "remaining": "123.00",
        "alreadypaid": "0.00",
        "currency": "PLN",
        "type": "invoice",
        "draft": "0",
        "is_rejected": "0",
        "contractor_detail": {"name": "Orange Polska S.A.", "nip": "5260250995"},
    }
    return {**base, **overrides}


def payment_dict(**overrides: Any) -> dict[str, Any]:
    """A payment against a tax declaration; ZUS payments carry the contribution split."""
    base: dict[str, Any] = {
        "id": "9001",
        "object_name": "declaration_header",
        "object_id": "127088694",
        "value": "800.00",
        "social": "0.00",
        "health": "0.00",
        "labor_fund": "0.00",
        "date": "2026-09-15",
        "type": "expense",
    }
    return {**base, **overrides}


def api_payload(
    module: str,
    entity: str,
    records: list[dict[str, Any]],
    *,
    total: int | None = None,
    page: int = 1,
    limit: int = 100,
    wrap: bool = False,
) -> dict[str, Any]:
    """A successful find/get response: {"invoices": {"0": {"invoice": {...}}, "parameters": ...}}."""
    collection: dict[str, Any] = {str(i): {entity: r} for i, r in enumerate(records)}
    collection["parameters"] = {
        "page": str(page),
        "limit": str(limit),
        "total": str(len(records) if total is None else total),
    }
    body = {module: collection, "status": {"code": "OK"}}
    return {"api": body} if wrap else body


def status_payload(code: str) -> dict[str, Any]:
    """A response carrying only a status code (how wFirma reports errors)."""
    return {"status": {"code": code}}
