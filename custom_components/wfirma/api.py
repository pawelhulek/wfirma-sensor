"""A thin async client for the parts of the wFirma API v2 this integration reads.

Request format, headers and status codes follow https://doc.wfirma.pl/.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping
from datetime import date
import json
from typing import Any

import aiohttp

from .const import API_BASE_URL, MAX_PAGES, PAGE_LIMIT, REQUEST_TIMEOUT
from .exceptions import (
    WfirmaAuthError,
    WfirmaConnectionError,
    WfirmaNotFoundError,
    WfirmaRateLimitError,
    WfirmaResponseError,
)
from .models import Company, Invoice

_AUTH_CODES = frozenset({"AUTH", "ACCESS DENIED"})
_RATE_LIMIT_CODES = frozenset({"TOTAL REQUESTS LIMIT EXCEEDED", "AUTH FAILED LIMIT WAIT 5 MINUTES"})
_NOT_FOUND_CODES = frozenset({"NOT FOUND"})


def _raise_for_code(code: str) -> None:
    """Map a wFirma status code to an exception; return quietly for OK."""
    if code == "OK":
        return
    if code in _AUTH_CODES:
        raise WfirmaAuthError(code)
    if code in _RATE_LIMIT_CODES:
        raise WfirmaRateLimitError(code)
    if code in _NOT_FOUND_CODES:
        raise WfirmaNotFoundError(code)
    raise WfirmaResponseError(code or "no status code")


def _parse(text: str) -> dict[str, Any]:
    """Decode a response body. Auth failures sometimes arrive as bare text."""
    stripped = text.strip()
    _raise_for_bare_status(stripped)
    try:
        parsed = json.loads(stripped)
    except ValueError as err:
        raise WfirmaResponseError("response is not JSON") from err
    if isinstance(parsed, str):
        _raise_for_bare_status(parsed.strip())
    if not isinstance(parsed, dict):
        raise WfirmaResponseError("unexpected response shape")
    payload = parsed.get("api", parsed)
    if not isinstance(payload, dict):
        raise WfirmaResponseError("unexpected response shape")
    status = payload.get("status")
    code = status.get("code", "") if isinstance(status, Mapping) else ""
    _raise_for_code(str(code).strip().upper())
    return payload


def _raise_for_bare_status(text: str) -> None:
    code = text.upper()
    if code in _AUTH_CODES or code in _RATE_LIMIT_CODES:
        _raise_for_code(code)


def _records(payload: Mapping[str, Any], module: str, entity: str) -> Iterator[Mapping[str, Any]]:
    """Yield records from {"invoices": {"0": {"invoice": {...}}, "parameters": {...}}}."""
    collection = payload.get(module)
    items: Any
    if isinstance(collection, Mapping):
        items = (v for k, v in collection.items() if k != "parameters")
    elif isinstance(collection, list):
        items = collection
    else:
        return
    for item in items:
        if isinstance(item, Mapping):
            record = item.get(entity, item)
            if isinstance(record, Mapping):
                yield record


def _total(payload: Mapping[str, Any], module: str) -> int | None:
    collection = payload.get(module)
    params = collection.get("parameters") if isinstance(collection, Mapping) else None
    try:
        return int(params["total"]) if isinstance(params, Mapping) else None
    except (KeyError, TypeError, ValueError):
        return None


def _companies(node: Any, found: dict[str, Company]) -> None:
    """Walk user_companies: records may be a relation wrapping the company."""
    if isinstance(node, list):
        for item in node:
            _companies(item, found)
        return
    if not isinstance(node, Mapping):
        return
    if any(node.get(k) for k in ("company_name", "company_id", "name", "altname", "nip")):
        company = Company.from_api(node)
        if company is not None and company.id not in found and (
            node.get("company_id") or node.get("name") or node.get("altname")
        ):
            found[company.id] = company
    for key, value in node.items():
        # A relation can embed the user who owns it; that is a person, not a company.
        if key in ("user", "users"):
            continue
        if isinstance(value, (Mapping, list)):
            _companies(value, found)


class WfirmaClient:
    """Reads invoices and companies. Instances are immutable; see with_company()."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        access_key: str,
        secret_key: str,
        app_key: str,
        company_id: str | None = None,
    ) -> None:
        self._session = session
        self._keys = (access_key, secret_key, app_key)
        self._headers = {
            "accessKey": access_key,
            "secretKey": secret_key,
            "appKey": app_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._company_id = company_id

    @property
    def company_id(self) -> str | None:
        return self._company_id

    def with_company(self, company_id: str | None) -> WfirmaClient:
        """A client for another company, sharing the session and keys."""
        return WfirmaClient(self._session, *self._keys, company_id)

    async def _request(
        self, module: str, action: str, body: Mapping[str, Any] | None = None, record_id: str | None = None
    ) -> dict[str, Any]:
        path = f"{API_BASE_URL}/{module}/{action}" + (f"/{record_id}" if record_id else "")
        params = {"inputFormat": "json", "outputFormat": "json"}
        if self._company_id:
            params["company_id"] = self._company_id
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                response = await self._session.post(path, params=params, json=body or {}, headers=self._headers)
                text = await response.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise WfirmaConnectionError(f"cannot reach wFirma: {err!r}") from err
        if response.status in (401, 403):
            raise WfirmaAuthError(f"HTTP {response.status}")
        if response.status >= 400:
            raise WfirmaConnectionError(f"HTTP {response.status}")
        return _parse(text)

    async def _find_all(
        self, module: str, entity: str, condition: Mapping[str, str] | None
    ) -> tuple[Mapping[str, Any], ...]:
        """Every record matching one condition, following pages up to MAX_PAGES."""
        pages: list[list[Mapping[str, Any]]] = []
        for page in range(1, MAX_PAGES + 1):
            parameters: dict[str, Any] = {"page": page, "limit": PAGE_LIMIT}
            if condition:
                parameters["conditions"] = {"condition": dict(condition)}
            payload = await self._request(module, "find", {module: {"parameters": parameters}})
            records = list(_records(payload, module, entity))
            pages.append(records)
            total = _total(payload, module)
            if len(records) < PAGE_LIMIT or (total is not None and page * PAGE_LIMIT >= total):
                break
        return tuple(record for page_records in pages for record in page_records)

    async def verify(self) -> None:
        """Cheapest call that proves the keys work."""
        await self._request("invoices", "find", {"invoices": {"parameters": {"page": 1, "limit": 1}}})

    async def list_companies(self) -> tuple[Company, ...]:
        payload = await self._request("user_companies", "find")
        found: dict[str, Company] = {}
        _companies(payload.get("user_companies"), found)
        return tuple(found.values())

    async def unpaid_invoices(self) -> tuple[Invoice, ...]:
        """Documents with an outstanding balance (doc.wfirma.pl: Invoice.remaining gt 0)."""
        condition = {"field": "Invoice.remaining", "operator": "gt", "value": "0"}
        return tuple(Invoice.from_api(r) for r in await self._find_all("invoices", "invoice", condition))

    async def invoices_issued_since(self, since: date) -> tuple[Invoice, ...]:
        condition = {"field": "Invoice.date", "operator": "ge", "value": since.isoformat()}
        return tuple(Invoice.from_api(r) for r in await self._find_all("invoices", "invoice", condition))

    async def get_invoice(self, invoice_id: str) -> Invoice | None:
        if not invoice_id.isdigit():
            raise ValueError("invoice id must be numeric")
        try:
            payload = await self._request("invoices", "get", record_id=invoice_id)
        except WfirmaNotFoundError:
            return None
        record = next(_records(payload, "invoices", "invoice"), None)
        return Invoice.from_api(record) if record is not None else None
