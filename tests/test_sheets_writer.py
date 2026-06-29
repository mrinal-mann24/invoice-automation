"""Tests for SheetsWriter — verifies row formatting without hitting Google API."""
from unittest.mock import MagicMock, patch

import pytest

from app.models.models import InvoiceRow
from app.services.sheets_writer import SheetsWriter, _HEADERS


def _make_row() -> InvoiceRow:
    return InvoiceRow(
        invoice_received_date="2024-01-15",
        invoice_date="2024-01-10",
        invoice_number="INV-001",
        vendor="Acme Corp",
        net_amount=44355.0,
        status="Paid",
        company_name="Interropac Private Limited",
        bank_name="State Bank of India",
        payment_date=None,
        vendor_bank_name="State Bank of India RT Nagar",
        account_number="37556010149",
        ifsc="SBIN0007982",
        message_id="msg-1",
    )


def _make_writer() -> tuple[SheetsWriter, MagicMock]:
    mock_ws = MagicMock()
    mock_sheet = MagicMock()
    mock_sheet.worksheet.return_value = mock_ws

    with patch("app.services.sheets_writer.get_settings") as mock_settings, \
         patch("app.services.sheets_writer.Credentials") as mock_creds, \
         patch("app.services.sheets_writer.gspread") as mock_gspread:

        mock_settings.return_value.service_account_path = "/fake/path.json"
        mock_settings.return_value.google_sheet_id = "fake-sheet-id"
        mock_creds.from_service_account_file.return_value = MagicMock()
        mock_gspread.authorize.return_value.open_by_key.return_value = mock_sheet

        writer = SheetsWriter()
        writer._ws = mock_ws
        return writer, mock_ws


class TestSheetsWriter:
    def test_append_calls_append_row(self):
        writer, mock_ws = _make_writer()
        writer.append(_make_row())
        mock_ws.append_row.assert_called_once()

    def test_append_row_has_correct_length(self):
        writer, mock_ws = _make_writer()
        writer.append(_make_row())
        args = mock_ws.append_row.call_args[0][0]
        assert len(args) == len(_HEADERS)

    def test_invoice_number_in_row(self):
        writer, mock_ws = _make_writer()
        writer.append(_make_row())
        args = mock_ws.append_row.call_args[0][0]
        assert args[_HEADERS.index("Invoice Number")] == "INV-001"

    def test_net_amount_in_row(self):
        writer, mock_ws = _make_writer()
        writer.append(_make_row())
        args = mock_ws.append_row.call_args[0][0]
        assert args[_HEADERS.index("Net amount")] == 44355.0

    def test_amount_is_blank(self):
        writer, mock_ws = _make_writer()
        writer.append(_make_row())
        args = mock_ws.append_row.call_args[0][0]
        assert args[_HEADERS.index("Amount")] == ""

    def test_tds_amount_is_blank(self):
        writer, mock_ws = _make_writer()
        writer.append(_make_row())
        args = mock_ws.append_row.call_args[0][0]
        assert args[_HEADERS.index("TDS amount")] == ""

    def test_status_always_paid(self):
        writer, mock_ws = _make_writer()
        writer.append(_make_row())
        args = mock_ws.append_row.call_args[0][0]
        assert args[_HEADERS.index("Status")] == "Paid"

    def test_none_fields_written_as_empty_string(self):
        row = _make_row()
        row.payment_date = None
        writer, mock_ws = _make_writer()
        writer.append(row)
        args = mock_ws.append_row.call_args[0][0]
        assert args[_HEADERS.index("Payment Date")] == ""
