"""Constants for the wFirma integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "wfirma"

CONF_ACCESS_KEY: Final = "access_key"
CONF_SECRET_KEY: Final = "secret_key"
CONF_APP_KEY: Final = "app_key"
CONF_COMPANY_ID: Final = "company_id"
CONF_COMPANY_NAME: Final = "company_name"

API_BASE_URL: Final = "https://api2.wfirma.pl"
REQUEST_TIMEOUT: Final = 30  # seconds
PAGE_LIMIT: Final = 100  # the API's maximum page size
MAX_PAGES: Final = 20  # hard stop: 2,000 records per query

SCAN_INTERVAL: Final = timedelta(minutes=30)
BASE_CURRENCY: Final = "PLN"
ATTRIBUTE_LIST_LIMIT: Final = 10

EVENT_INVOICE_PAID: Final = "wfirma_invoice_paid"

# Documents that are not sales: they never count as unpaid or as revenue.
NON_SALES_TYPES: Final = frozenset(
    {"proforma", "proforma_bill", "offer", "offer_bill", "normal_draft"}
)
