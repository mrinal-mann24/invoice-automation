from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

# Maps mailbox label → company name shown in the sheet
COMPANY_NAME_MAP = {
    "mailbox1": "Interropac Private Limited",
    "mailbox2": "Jayshree Dealer Private Limited",
}


class EmailRecord(BaseModel):
    message_id: str
    subject: str
    sender: str
    received_datetime: datetime
    mailbox_source: str  # "mailbox1" | "mailbox2"


class AttachmentRecord(BaseModel):
    message_id: str
    mailbox_source: str
    subject: str
    sender: str
    received_datetime: datetime
    filename: str
    local_path: Path
    content_type: str


class InvoiceRow(BaseModel):
    """One row in the Google Sheet / Supabase table."""

    # ── Filled by the pipeline ──────────────────────────────────────────
    invoice_received_date: str = ""      # date email arrived
    company_name: str = ""               # derived from mailbox_source
    status: str = "Paid"                 # always Paid
    message_id: str = ""                 # for internal tracing only

    # ── Filled by GPT-4o ────────────────────────────────────────────────
    invoice_date: Optional[str] = None
    invoice_number: Optional[str] = None
    vendor: Optional[str] = None
    net_amount: Optional[float] = None   # total as printed on the bill
    currency_symbol: Optional[str] = None # e.g. $, €, ₹, £
    bank_name: Optional[str] = None
    payment_date: Optional[str] = None
    vendor_bank_name: Optional[str] = None
    account_number: Optional[str] = None
    ifsc: Optional[str] = None

    # ── Internal / audit ────────────────────────────────────────────────
    document_type: Optional[str] = None  # Invoice / Utility Bill / Breakdown / Other
    raw_gpt_response: Optional[str] = None
    error: Optional[str] = None
