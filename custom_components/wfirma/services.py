"""Actions: download an invoice PDF, and list open documents and upcoming deadlines."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_NUMBER,
    DEADLINES_IN_ACTION,
    DOMAIN,
    DOWNLOAD_SUBDIR,
    SERVICE_DOWNLOAD_INVOICE,
    SERVICE_GET_DOCUMENTS,
)
from .coordinator import Snapshot, WfirmaConfigEntry
from .exceptions import WfirmaError

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

_ENTRY = {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}
DOWNLOAD_SCHEMA = vol.Schema({**_ENTRY, vol.Required(ATTR_NUMBER): vol.All(cv.string, vol.Length(min=1, max=64))})
DOCUMENTS_SCHEMA = vol.Schema(_ENTRY)


def _error(key: str, **placeholders: str) -> ServiceValidationError:
    return ServiceValidationError(translation_domain=DOMAIN, translation_key=key, translation_placeholders=placeholders)


def _entry(hass: HomeAssistant, call: ServiceCall) -> WfirmaConfigEntry:
    """The company the call names, or the only one there is."""
    loaded = [e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED]
    wanted = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if wanted is not None:
        loaded = [e for e in loaded if e.entry_id == wanted]
    if len(loaded) != 1:
        raise _error("choose_company" if len(loaded) > 1 else "no_company")
    return loaded[0]


def safe_filename(number: str) -> str:
    """"FV 3/9/2026" -> "FV_3_9_2026.pdf"; never a path."""
    return (_UNSAFE.sub("_", number).strip("._") or "invoice") + ".pdf"


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


async def _download_invoice(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    client = _entry(hass, call).runtime_data.client
    number: str = call.data[ATTR_NUMBER].strip()
    media = hass.config.media_dirs.get("local") or hass.config.path("media")
    target = Path(media) / DOWNLOAD_SUBDIR / safe_filename(number)
    if not hass.config.is_allowed_path(str(target)):
        raise _error("path_not_allowed", path=str(target.parent))
    try:
        invoice = await client.find_invoice(number)
        if invoice is None:
            raise _error("invoice_not_found", number=number)
        content = await client.download_invoice(invoice.id)
    except WfirmaError as err:
        raise _error("download_failed", number=number, reason=str(err)) from err
    await hass.async_add_executor_job(_write, target, content)
    return {"number": invoice.number, "path": str(target), "size": len(content)}


def documents(snapshot: Snapshot) -> dict[str, Any]:
    """Open documents and the next deadlines, straight from the last poll."""
    today = snapshot.today
    pending = [d for d in snapshot.deadlines or () if d.paid is not True and (d.due >= today or d.is_overdue(today))]
    return {
        "unpaid_invoices": snapshot.invoices.unpaid_attributes(),
        "overdue_invoices": snapshot.invoices.overdue_attributes(),
        "unpaid_expenses": snapshot.expenses.unpaid_attributes() if snapshot.expenses else None,
        "deadlines": [
            {
                "kind": d.kind.value,
                "period": f"{d.period.year}-{d.period.month:02d}",
                "due": d.due.isoformat(),
                "paid": d.paid,
                "overdue": d.is_overdue(today),
            }
            for d in pending[:DEADLINES_IN_ACTION]
        ],
    }


async def _get_documents(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    return documents(_entry(hass, call).runtime_data.data)


def async_setup_services(hass: HomeAssistant) -> None:
    async def download(call: ServiceCall) -> ServiceResponse:
        return await _download_invoice(hass, call)

    async def get_documents(call: ServiceCall) -> ServiceResponse:
        return await _get_documents(hass, call)

    hass.services.async_register(
        DOMAIN, SERVICE_DOWNLOAD_INVOICE, download, schema=DOWNLOAD_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN, SERVICE_GET_DOCUMENTS, get_documents, schema=DOCUMENTS_SCHEMA, supports_response=SupportsResponse.ONLY
    )
