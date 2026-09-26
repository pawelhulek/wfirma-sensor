# wFirma for Home Assistant — design

## Product (PRD)

**Problem.** wFirma holds the state of a small business's money — which clients still owe what, what is
overdue, how much has been invoiced this month — but none of it reaches Home Assistant, so it cannot drive
dashboards or reminders.

**Users.** A wFirma account owner running Home Assistant (single company or an accounting-office account
with several client companies).

**Must have (v0.1)**
| Entity / event | Meaning |
|---|---|
| `sensor.<co>_unpaid_invoices` | number of issued sales documents with an outstanding balance |
| `sensor.<co>_unpaid_amount` | sum of outstanding balances (PLN) |
| `sensor.<co>_overdue_invoices` | unpaid documents past their payment date |
| `sensor.<co>_overdue_amount` | sum of overdue balances (PLN) |
| `sensor.<co>_revenue_this_month_net` / `_gross` | sales documents issued since the 1st of the month (PLN) |
| event `wfirma_invoice_paid` | fired when a previously unpaid invoice is confirmed paid |

Setup through the UI (config flow), re-authentication when keys stop working, diagnostics with secrets
redacted, English and Polish translations.

**Out of scope for v0.1:** writing to wFirma, taxes due (VAT/PIT/ZUS — not confirmed in the public docs),
expenses, OAuth.

## Architecture

```
config_flow ──validates──▶ api.WfirmaClient ◀──polls── coordinator (DataUpdateCoordinator, 30 min)
                                  │                           │
                          models.Invoice (frozen)      summary.summarize() (pure)
                                                              │
                                              sensor entities + wfirma_invoice_paid event
```

- `api.py` — thin async client on HA's shared aiohttp session. No third-party dependency: the only PyPI
  SDK is 0.0.6 and synchronous, and the surface needed is four calls.
- `models.py` — frozen dataclasses parsed from API dicts; money as `Decimal`.
- `summary.py` — pure functions (no I/O) that turn invoices into the sensor values; fully unit-tested.
- `coordinator.py` — fetches, summarises, detects invoices that left the unpaid set and confirms each
  with `invoices/get` before firing `wfirma_invoice_paid` (a deleted invoice must not look paid).

## API facts (with sources)

| Fact | Source |
|---|---|
| Base `https://api2.wfirma.pl/{module}/{action}[/{id}]?inputFormat=json&outputFormat=json[&company_id=]` | doc.wfirma.pl; agente-dev/wfirma-mcp `src/client.ts` |
| Auth headers `accessKey`, `secretKey`, `appKey` (appKey issued by wFirma on request) | doc.wfirma.pl "Autoryzacja" |
| JSON records: `{"invoices": {"0": {"invoice": {…}}, "parameters": {"page","limit","total"}}, "status": {"code": "OK"}}`, optionally wrapped in `{"api": …}` | doc.wfirma.pl; wfirma-mcp |
| Errors: `status.code` ≠ `OK` (`ERROR`, `FATAL`, `ACCESS DENIED`, `AUTH`, `TOTAL REQUESTS LIMIT EXCEEDED`…); auth failures may be a bare text body (`AUTH`, `ACCESS DENIED`, `AUTH FAILED LIMIT WAIT 5 MINUTES`) | doc.wfirma.pl "Komunikaty błędów"; wfirma-mcp |
| Unpaid filter `Invoice.remaining gt 0` | doc.wfirma.pl "Złożone warunki logiczne" |
| Invoice fields `fullnumber, date, paymentdate, paymentstate, total, netto, tax, remaining, alreadypaid, currency, type, contractor_detail` | dbojdo/wFirma `src/Invoices/Invoice.php` |
| `paymentstate` ∈ `paid, unpaid, undefined`; `type` ∈ `normal, bill, correction, receipt_*, income_*, proforma*, offer*, normal_draft` | dbojdo/wFirma `PaymentState.php`, `Type.php` |
| Pages of up to 100 | wfirma-mcp |

## Risks and how the design absorbs them

1. **JSON shape of several conditions is undocumented.** Each query uses a single condition, and every
   result is filtered again client-side, so the sensors stay correct even if the API ignored the filter.
2. **Mixed currencies.** Amount sensors are PLN only; other currencies are reported per currency in the
   attributes rather than summed into PLN.
3. **Non-revenue documents** (pro-formas, offers, drafts) are excluded from every figure.
4. **Rate limits.** 30-minute polling, at most 20 pages per query, and `TOTAL REQUESTS LIMIT EXCEEDED` /
   `AUTH FAILED LIMIT…` are treated as temporary failures, never as bad credentials.
5. **Not verified against a live account yet** — the user must first obtain an appKey from wFirma.

## Tasks
1. Tests + `models.py`, `summary.py` (pure logic)
2. Tests + `api.py` (request shape, paging, every error path)
3. Tests + config flow (single/multiple/no companies, errors, re-auth)
4. Tests + coordinator, sensors, paid event, diagnostics, setup/unload
5. Manifest, translations, HACS metadata, CI (pytest, hassfest), README
6. Review, publish to GitHub, install on the user's Home Assistant
