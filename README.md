# wFirma for Home Assistant

Brings your [wFirma](https://wfirma.pl) books into Home Assistant: who still owes you money, which bills
you still have to pay, when ZUS, income tax and VAT are due, and how much you have invoiced this month.
There is also a calendar of all those dates, an event when a client pays, and an action that saves an
invoice as a PDF.

Read-only. It never creates or changes anything in wFirma.

## What you get

| Entity | Shows |
|---|---|
| Unpaid invoices | Number of issued sales documents with money still outstanding. Attribute `invoices` lists up to 10, oldest due date first. |
| Unpaid amount | Total outstanding, in PLN |
| Overdue invoices | Unpaid documents past their payment date, with the same list |
| Overdue amount | Total overdue, in PLN |
| Revenue this month (net / gross) | Sales documents issued since the 1st of the month, in PLN. Attribute `documents` is how many. |
| Bills to pay / Bills to pay amount | Cost invoices (wFirma *Wydatki*) with money still to pay. Attributes: `expenses` (up to 10, soonest due first), `overdue`, `next_due`. Drafts and rejected documents are ignored. |
| Next ZUS payment | Date the next ZUS contributions are due. Attributes: `period`, `paid`, `overdue`, `days_left`, `estimated_amount` (your last ZUS payment), `last_payment_date`. |
| Next income tax payment | Date the next ryczałt / PIT advance / tax card instalment is due, with `period`, `days_left`, `tax_form`. |
| Next VAT payment | Date the next VAT (JPK_V7M) is due. Only for VAT payers. |
| Payments and taxes (calendar) | All-day events: ZUS, income tax and VAT deadlines, your clients' payment dates and your bills' due dates. |

Pro-formas, offers and drafts are never counted. Corrections are included, so a correction lowers
revenue. Invoices in other currencies are counted, and their totals are listed in the `other_currencies`
attribute instead of being converted into PLN.

Data refreshes every 30 minutes.

### How the tax deadlines work

wFirma's API does not publish upcoming tax amounts or deadlines, so they are worked out from the law and
your company settings in wFirma (tax form, VAT payer):

- **ZUS**: the 20th of the following month.
- **Income tax**: the 20th of the following month for ryczałt and PIT (December's also by 20 January, the
  earlier of the allowed dates), the 7th for the tax card (December's by 28 December).
- **VAT**: the 25th of the following month (monthly JPK_V7M; quarterly filers are not supported yet).

A date on a weekend or public holiday moves to the next working day (Tax Ordinance art. 12 §5).

**Paid or not.** A ZUS payment you mark as paid in wFirma counts for the month before the one you paid in
(paying on 13 August settles July). If wFirma has no ZUS payments at all, the status is unknown rather
than overdue. Income-tax and VAT payments look the same in wFirma's data, so their status is always
unknown: the sensors only tell you the date.

### Calendar reminders

```yaml
automation:
  - alias: "Tax and payment reminders"
    triggers:
      - trigger: calendar
        event: start
        entity_id: calendar.your_company_payments_and_taxes
        offset: "-3:00:00:00"  # three days before
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: "{{ trigger.calendar_event.summary }}"
          message: "Due {{ trigger.calendar_event.start }}. {{ trigger.calendar_event.description }}"
```

### Actions

**`wfirma.download_invoice`** saves a sales invoice as a PDF under the media folder
(`media/wfirma/FV_3_9_2026.pdf`), so it shows up in *Media → My media*. It returns the saved path.

```yaml
action: wfirma.download_invoice
data:
  number: "FV 3/9/2026"
```

**`wfirma.get_documents`** returns unpaid and overdue sales invoices, bills to pay and the next six
deadlines from the last refresh. It makes no call to wFirma, so it is cheap to use in scripts or
dashboards.

With several companies, add `config_entry_id` to either action.

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
- Tax and ZUS **amounts** are not available from wFirma's API; the ZUS figure is your last payment.
- VAT is assumed monthly (JPK_V7M).
- If your keys cannot read cost invoices or payments, those entities are unavailable and the invoice
  sensors carry on.
- A query stops after 2,000 documents, which only matters for very large accounts.
- For accounts whose keys don't list companies, use *Reconfigure* after rotating keys. Adding the
  integration again would create a second copy of the same company.

## Development

```bash
python3.14 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest --cov=custom_components/wfirma
```

Design notes, API sources and risks are in [docs/DESIGN.md](docs/DESIGN.md).
