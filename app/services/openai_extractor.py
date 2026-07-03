"""
Sends each attachment to GPT-4o vision and returns a structured InvoiceRow.

PDFs  → rendered page-by-page to PNG via PyMuPDF, then sent as images.
Images → sent directly as base64.

Breakdowns / non-invoice documents are detected and returned as None
so the caller can skip them.
"""
import base64
import json
from pathlib import Path

import fitz  # PyMuPDF
from loguru import logger
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config.settings import get_settings
from app.models.models import AttachmentRecord, InvoiceRow, COMPANY_NAME_MAP


_SYSTEM_PROMPT = """You are a strict invoice data extraction assistant for an Indian company's accounts payable team.

You will receive one or more images of a business document.

FIRST decide what type of document this is:
- "Invoice"              → a general bill/invoice requesting payment (goods, materials, products)
- "Professional Bill"    → consultancy, professional services, manpower, staffing, advisory fees
- "Rent"                 → office rent, table space, co-working space, property rental invoices
- "Contract"             → contract-based services, AMC, maintenance contracts, retainer agreements
- "Software"             → software licenses, SaaS subscriptions, IT services, cloud services
- "Utility Bill"         → electricity, water, internet, telephone, maintenance society bills
- "Reimbursement"        → expense reimbursement claims, travel expenses, petty cash, out-of-pocket cost recovery bills
- "Breakdown"            → a supporting schedule, annexure, or breakdown sheet (NOT a payable document on its own)
- "Other"                → anything that is clearly NOT a bill or invoice (PO, delivery note, statement, recall notice, etc.)

If the document is a Breakdown or Other — return ONLY:
{"document_type": "Breakdown"}   or   {"document_type": "Other"}

If the document type is Invoice, Professional Bill, Rent, Contract, Software, Utility Bill, or Reimbursement — extract ALL of the following and return ONLY valid JSON (no markdown):
{
  "document_type": "Invoice" | "Utility Bill",
  "invoice_number": null,
  "invoice_date": null,
  "vendor_name": null,
  "total_amount": null,
  "currency_symbol": null,
  "bank_name": null,
  "payment_date": null,
  "vendor_bank_name": null,
  "account_number": null,
  "ifsc": null
}

Strict rules:
- Dates must be in YYYY-MM-DD format. If only month/year visible use YYYY-MM-01.
- Monetary values: plain number, no currency symbol, no commas (e.g. 44355.00). NEVER put a date in total_amount — if unsure, use null.
- total_amount = the final grand total payable on the invoice (including taxes). It must be a number only.
- currency_symbol = the symbol of the currency used on the invoice. Use exactly: "$" for USD, "€" for EUR, "₹" for INR, "£" for GBP. Detect from symbols or explicit currency text on the document. If genuinely unclear, use null.
- payment_date = ONLY fill this if the document explicitly shows a date when payment was made or is due. If not clearly visible, use null. Do NOT guess or use invoice_date as payment_date.
- Bank details: look for NEFT/RTGS instructions, "transfer to", "pay to" sections.
- IFSC: typically looks like SBIN0007982 or ICIC0000002.
- Account number: numeric string, often 9-18 digits.
- If a field is genuinely not present in the document, use null — never guess or invent.
- Do NOT include any text outside the JSON object.
"""


class OpenAIExtractor:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def extract(self, record: AttachmentRecord) -> InvoiceRow | None:
        """
        Returns an InvoiceRow if the document is an invoice/utility bill.
        Returns None if it is a breakdown or unsupported document type.
        """
        row = InvoiceRow(
            invoice_received_date=record.received_datetime.strftime("%Y-%m-%d"),
            company_name=COMPANY_NAME_MAP.get(record.mailbox_source, record.mailbox_source),
            message_id=record.message_id,
        )

        try:
            image_parts = self._build_image_messages(record.local_path)
        except Exception as exc:
            logger.error("Image prep failed for {}: {}", record.filename, exc)
            row.error = f"Image prep failed: {exc}"
            return row

        if not image_parts:
            row.error = "Could not render document to images"
            return row

        logger.info(
            "[{}] Sending {} to GPT-4o ({} page(s))",
            record.mailbox_source, record.filename, len(image_parts),
        )

        try:
            response = await self._client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": image_parts},
                ],
                max_tokens=800,
                temperature=0,
            )
            raw = response.choices[0].message.content.strip()
            row.raw_gpt_response = raw
        except Exception as exc:
            logger.error("GPT-4o call failed for {}: {}", record.filename, exc)
            row.error = f"GPT-4o error: {exc}"
            return row

        return self._parse(raw, row, record.filename)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse(self, raw: str, row: InvoiceRow, filename: str) -> InvoiceRow | None:
        try:
            clean = (
                raw.strip()
                .removeprefix("```json")
                .removeprefix("```")
                .removesuffix("```")
                .strip()
            )
            data: dict = json.loads(clean)
        except json.JSONDecodeError as exc:
            logger.warning("JSON parse error for {}: {}", filename, exc)
            row.error = f"JSON parse error: {exc}"
            return row

        doc_type = (data.get("document_type") or "").strip()
        row.document_type = doc_type

        if doc_type.lower() in ("breakdown", "other", ""):
            logger.info("Skipping {} — classified as '{}'", filename, doc_type)
            return None

        row.invoice_number   = _str(data.get("invoice_number"))
        row.invoice_date     = _str(data.get("invoice_date"))
        row.vendor           = _str(data.get("vendor_name"))
        row.net_amount       = _float(data.get("total_amount"))
        row.currency_symbol  = _str(data.get("currency_symbol"))
        row.bank_name        = _str(data.get("bank_name"))
        row.payment_date     = _str(data.get("payment_date"))
        row.vendor_bank_name = _str(data.get("vendor_bank_name"))
        row.account_number   = _str(data.get("account_number"))
        row.ifsc             = _str(data.get("ifsc"))

        return row

    def _build_image_messages(self, path: Path) -> list[dict]:
        if path.suffix.lower() == ".pdf":
            return self._pdf_to_images(path)
        return [self._image_to_part(path)]

    def _pdf_to_images(self, path: Path) -> list[dict]:
        parts: list[dict] = []
        doc = fitz.open(str(path))
        try:
            if doc.needs_pass:
                raise ValueError("PDF is password-protected / encrypted")
            for page_num, page in enumerate(doc, start=1):
                pix = page.get_pixmap(dpi=150)
                b64 = base64.b64encode(pix.tobytes("png")).decode()
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
                })
                logger.debug("Rendered page {}/{} of {}", page_num, len(doc), path.name)
        finally:
            doc.close()
        return parts

    def _image_to_part(self, path: Path) -> dict:
        # Normalize every image to PNG. GPT-4o only accepts png/jpeg/gif/webp —
        # TIFF/BMP (and some malformed JPEGs) are rejected with a 400 if sent raw.
        # Rendering through PyMuPDF also validates the bytes are a real image.
        doc = fitz.open(str(path))
        try:
            pix = doc[0].get_pixmap(dpi=150)
            png_bytes = pix.tobytes("png")
        finally:
            doc.close()
        b64 = base64.b64encode(png_bytes).decode()
        return {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
        }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _str(value: object) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s and s.lower() not in ("null", "none", "") else None


def _float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return None
