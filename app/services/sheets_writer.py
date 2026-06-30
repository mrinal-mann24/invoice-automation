"""Appends InvoiceRow records to a Google Sheet."""
import threading

import json

import gspread
from google.oauth2.service_account import Credentials
from loguru import logger

from app.config.settings import get_settings
from app.models.models import InvoiceRow

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Exact column order matching the user's sheet layout.
# Amount and TDS Amount are kept as blank columns — filled manually later.
_HEADERS = [
    "Invoice Received Date",
    "Invoice Date",
    "Invoice Number",
    "Vendor",
    "Amount",           # always blank — filled manually
    "Status",           # always blank — dropdown filled manually
    "Company Name",
    "TDS amount",       # always blank — filled manually
    "Net amount",       # total as on the bill
    "Bank Name",
    "Payment Date",
    "Vendor Bank Name",
    "A/c",
    "IFSC",
]

_WORKSHEET_NAME = "Invoice Register"

_lock = threading.Lock()


class SheetsWriter:
    def __init__(self) -> None:
        settings = get_settings()
        service_account_info = json.loads(
            settings.google_service_account_json.get_secret_value()
        )
        creds = Credentials.from_service_account_info(
            service_account_info,
            scopes=_SCOPES,
        )
        gc = gspread.authorize(creds)
        self._sheet = gc.open_by_key(settings.google_sheet_id)
        self._ws = self._get_or_create_worksheet()

    def _get_or_create_worksheet(self) -> gspread.Worksheet:
        try:
            ws = self._sheet.worksheet(_WORKSHEET_NAME)
        except gspread.WorksheetNotFound:
            ws = self._sheet.add_worksheet(
                title=_WORKSHEET_NAME, rows=1000, cols=len(_HEADERS)
            )
            logger.info("Created worksheet '{}'", _WORKSHEET_NAME)

        # Always ensure row 1 has headers — handles case where sheet existed but was empty
        first_row = ws.row_values(1)
        if not first_row or first_row[0] != _HEADERS[0]:
            ws.insert_row(_HEADERS, index=1, value_input_option="RAW")

            logger.info("Headers written to '{}'", _WORKSHEET_NAME)

        return ws

    def append(self, row: InvoiceRow) -> None:
        values = [
            row.invoice_received_date or "",
            row.invoice_date or "",
            row.invoice_number or "",
            row.vendor or "",
            "",                                                      # Amount — blank
            "",                                                      # Status — blank, dropdown filled manually
            row.company_name,
            "",                                                      # TDS amount — blank
            f"{row.currency_symbol}{row.net_amount}" if row.net_amount is not None else "",  # Net amount
            row.bank_name or "",
            row.payment_date or "",
            row.vendor_bank_name or "",
            row.account_number or "",
            row.ifsc or "",
        ]
        with _lock:
            self._ws.append_row(values, value_input_option="RAW")
        logger.info(
            "Sheet row appended — {} | {} | Net: {}",
            row.company_name, row.invoice_number or "no-inv#", row.net_amount,
        )
