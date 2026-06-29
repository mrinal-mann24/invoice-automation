"""Tests for OpenAIExtractor — parsing logic (TDS removed)."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models.models import AttachmentRecord, InvoiceRow
from app.services.openai_extractor import OpenAIExtractor, _float, _str
import datetime


def _make_record(filename: str = "invoice.pdf") -> AttachmentRecord:
    return AttachmentRecord(
        message_id="msg-1",
        mailbox_source="mailbox1",
        subject="Test Invoice",
        sender="vendor@example.com",
        received_datetime=datetime.datetime(2024, 1, 15, 9, 0, 0),
        filename=filename,
        local_path=Path(f"/tmp/{filename}"),
        content_type="application/pdf",
    )


def _mock_extractor() -> OpenAIExtractor:
    with patch("app.services.openai_extractor.get_settings") as mock_s:
        mock_s.return_value.openai_api_key.get_secret_value.return_value = "sk-test"
        with patch("app.services.openai_extractor.AsyncOpenAI"):
            return OpenAIExtractor()


def _base_row() -> InvoiceRow:
    return InvoiceRow(
        invoice_received_date="2024-01-15",
        company_name="Interropac Private Limited",
        message_id="msg-1",
    )


class TestParseMethod:
    def setup_method(self):
        self.extractor = _mock_extractor()

    def test_parses_full_invoice(self):
        raw = json.dumps({
            "document_type": "Invoice",
            "invoice_number": "INV-001",
            "invoice_date": "2024-01-10",
            "vendor_name": "Acme Corp",
            "total_amount": 44355.0,
            "bank_name": "State Bank of India",
            "payment_date": None,
            "vendor_bank_name": "SBI RT Nagar",
            "account_number": "37556010149",
            "ifsc": "SBIN0007982",
        })
        row = self.extractor._parse(raw, _base_row(), "invoice.pdf")
        assert row is not None
        assert row.invoice_number == "INV-001"
        assert row.vendor == "Acme Corp"
        assert row.net_amount == 44355.0
        assert row.account_number == "37556010149"
        assert row.ifsc == "SBIN0007982"

    def test_breakdown_returns_none(self):
        raw = json.dumps({"document_type": "Breakdown"})
        result = self.extractor._parse(raw, _base_row(), "breakdown.pdf")
        assert result is None

    def test_other_returns_none(self):
        raw = json.dumps({"document_type": "Other"})
        result = self.extractor._parse(raw, _base_row(), "other.pdf")
        assert result is None

    def test_invalid_json_sets_error(self):
        row = self.extractor._parse("not json", _base_row(), "bad.pdf")
        assert row is not None
        assert row.error is not None

    def test_strips_markdown_fences(self):
        raw = "```json\n" + json.dumps({
            "document_type": "Invoice",
            "invoice_number": "INV-999",
            "invoice_date": None, "vendor_name": None,
            "total_amount": 1000.0, "bank_name": None,
            "payment_date": None, "vendor_bank_name": None,
            "account_number": None, "ifsc": None,
        }) + "\n```"
        row = self.extractor._parse(raw, _base_row(), "invoice.pdf")
        assert row is not None
        assert row.invoice_number == "INV-999"

    def test_utility_bill_sets_net_amount(self):
        raw = json.dumps({
            "document_type": "Utility Bill",
            "invoice_number": "UB-001",
            "invoice_date": "2024-01-10",
            "vendor_name": "BESCOM",
            "total_amount": 44355.0,
            "bank_name": None, "payment_date": None,
            "vendor_bank_name": None, "account_number": None, "ifsc": None,
        })
        row = self.extractor._parse(raw, _base_row(), "utility.pdf")
        assert row is not None
        assert row.net_amount == 44355.0
        assert row.document_type == "Utility Bill"

    def test_invoice_sets_net_amount(self):
        raw = json.dumps({
            "document_type": "Invoice",
            "invoice_number": "INV-X",
            "invoice_date": None, "vendor_name": None,
            "total_amount": 5000.0, "bank_name": None,
            "payment_date": None, "vendor_bank_name": None,
            "account_number": None, "ifsc": None,
        })
        row = self.extractor._parse(raw, _base_row(), "invoice.pdf")
        assert row is not None
        assert row.net_amount == 5000.0


class TestHelpers:
    def test_str_none(self):
        assert _str(None) is None

    def test_str_null_string(self):
        assert _str("null") is None

    def test_str_valid(self):
        assert _str("  SBIN0007982  ") == "SBIN0007982"

    def test_float_valid(self):
        assert _float("44,355.00") == 44355.0

    def test_float_none(self):
        assert _float(None) is None


class TestExtractErrors:
    @pytest.mark.asyncio
    async def test_image_prep_failure_returns_error_row(self):
        extractor = _mock_extractor()
        record = _make_record()
        with patch.object(extractor, "_build_image_messages", side_effect=RuntimeError("fail")):
            row = await extractor.extract(record)
        assert row is not None
        assert row.error is not None

    @pytest.mark.asyncio
    async def test_no_images_returns_error_row(self):
        extractor = _mock_extractor()
        record = _make_record()
        with patch.object(extractor, "_build_image_messages", return_value=[]):
            row = await extractor.extract(record)
        assert row is not None
        assert row.error is not None
