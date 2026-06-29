"""Supabase integration — insert invoice rows and deduplicate by invoice_number."""
import threading

from loguru import logger
from supabase import create_client, Client

from app.config.settings import get_settings
from app.models.models import InvoiceRow

TABLE = "invoices"

_lock = threading.Lock()


class SupabaseWriter:
    def __init__(self) -> None:
        settings = get_settings()
        self._client: Client = create_client(
            settings.supabase_url,
            settings.supabase_key.get_secret_value(),
        )

    def is_duplicate(self, invoice_number: str) -> bool:
        """Return True if this invoice_number already exists in the table."""
        try:
            result = (
                self._client.table(TABLE)
                .select("invoice_number")
                .eq("invoice_number", invoice_number)
                .limit(1)
                .execute()
            )
            return len(result.data) > 0
        except Exception as exc:
            logger.warning("Supabase dedup check failed for {}: {}", invoice_number, exc)
            return False  # on error, allow the insert to proceed

    def insert(self, row: InvoiceRow) -> bool:
        """
        Insert one InvoiceRow into Supabase.
        Returns True on success, False on failure.
        """
        payload = {
            "invoice_received_date": row.invoice_received_date or None,
            "invoice_date": row.invoice_date,
            "invoice_number": row.invoice_number,
            "vendor": row.vendor,
            "net_amount": row.net_amount,
            "status": row.status,
            "company_name": row.company_name,
            "bank_name": row.bank_name,
            "payment_date": row.payment_date,
            "vendor_bank_name": row.vendor_bank_name,
            "account_number": row.account_number,
            "ifsc": row.ifsc,
            "document_type": row.document_type,
            "message_id": row.message_id,
            "error": row.error,
        }
        try:
            with _lock:
                self._client.table(TABLE).insert(payload).execute()
            logger.info("Supabase insert OK — invoice_number={}", row.invoice_number or "null")
            return True
        except Exception as exc:
            logger.error("Supabase insert failed: {}", exc)
            return False
