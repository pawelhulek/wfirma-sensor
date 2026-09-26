# wFirma for Home Assistant

Brings your [wFirma](https://wfirma.pl) invoices into Home Assistant: who still owes you money, what is
overdue, and how much you have invoiced this month, plus an event when a client pays.

Read-only. It never creates or changes anything in wFirma.

## What you get

| Entity | Shows |
|---|---|
| Unpaid invoices | Number of issued sales documents with money still outstanding. Attribute `invoices` lists up to 10, oldest due date first. |
| Unpaid amount | Total outstanding, in PLN |
| Overdue invoices | Unpaid documents past their payment date, with the same list |
| Overdue amount | Total overdue, in PLN |
| Revenue this month (net / gross) | Sales documents issued since the 1st of the month, in PLN. Attribute `documents` is how many. |

Pro-formas, offers and drafts are never counted. Corrections are included, so a correction lowers
revenue. Invoices in other currencies are counted, and their totals are listed in the `other_currencies`
attribute instead of being converted into PLN.

Data refreshes every 30 minutes.

### Event: `wfirma_invoice_paid`

Fired when an invoice that was unpaid at the previous refresh is confirmed paid in wFirma. An invoice
that disappears for another reason (deleted, turned into a draft) does not fire it.

```yaml
automation:
  - alias: "Tell me when a client pays"
    triggers:
      - trigger: event
        event_type: wfirma_invoice_paid
    actions:
      - action: notify.mobile_app_your_phone
        data:
          message: >
            {{ trigger.event.data.contractor }} paid {{ trigger.event.data.number }}:
            {{ trigger.event.data.amount }} {{ trigger.event.data.currency }}
```

Event data: `invoice_id`, `number`, `contractor`, `amount` (gross), `currency`, `company`.

## Before you install: get three keys

wFirma's API needs three keys ([wFirma docs](https://doc.wfirma.pl/#autoryzacja)):

1. **Access key** and **secret key**: in wFirma, open *Settings → Security* and create API keys. The
   secret key is shown only once; copy it straight away.
2. **App key**: wFirma issues this one on request for API access. Ask their support for an app key for
   your own integration.

## Installation

**HACS (recommended):** HACS → ⋮ → *Custom repositories* → add
`https://github.com/pawelhulek/wfirma-sensor` as an *Integration* → install **wFirma** → restart Home
Assistant.

**Manually:** copy `custom_components/wfirma` into your Home Assistant `config/custom_components/` and
restart.

Then *Settings → Devices & services → Add integration → wFirma* and enter the three keys. If the keys can
open several companies (an accounting-office account), you choose one; add the integration again for
another.

## When the keys stop working

Home Assistant shows a *Reconfigure* notice. Enter new keys there; the entities keep their history.

## Limits

- Figures are summed in PLN only; other currencies are listed separately.
- Taxes due (VAT, PIT, ZUS) and expenses are not included.
- A query stops after 2,000 documents, which only matters for very large accounts.
- For accounts whose keys don't list companies, use *Reconfigure* after rotating keys. Adding the
  integration again would create a second copy of the same company.

## Development

```bash
python3.14 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest --cov=custom_components/wfirma
```

Design notes, API sources and risks are in [docs/DESIGN.md](docs/DESIGN.md).
