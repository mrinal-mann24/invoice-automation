"""
Invoice Automation — continuous polling loop.

Checks both mailboxes every POLL_INTERVAL_MINUTES for new unread emails.
Runs forever until you press Ctrl+C.

Usage:
    uv run python main.py
"""
import asyncio
from loguru import logger

from app.config.logging import configure_logging
from app.config.settings import get_settings
from app.graph.mail_client import MailboxClient
from app.models.models import InvoiceRow
from app.services.attachment_handler import AttachmentHandler
from app.services.openai_extractor import OpenAIExtractor
from app.services.sheets_writer import SheetsWriter
from app.services.supabase_client import SupabaseWriter

POLL_INTERVAL_MINUTES = 1


async def process_mailbox(
    client: MailboxClient,
    extractor: OpenAIExtractor,
    sheets: SheetsWriter,
    db: SupabaseWriter,
) -> int:
    """Run the full pipeline for one mailbox. Returns count of rows written."""
    handler = AttachmentHandler(client)
    rows_written = 0

    emails = await client.fetch_todays_unread_emails()
    if not emails:
        logger.info("[{}] No new unread emails", client.label)
        return 0

    for email in emails:
        logger.info("[{}] Processing: '{}'", client.label, email.subject)

        attachments = await handler.download_for_email(email)

        # Mark as read immediately after download — prevents re-processing
        # if a crash happens mid-extraction on the next run. Email stays in Inbox.
        await client.mark_read(email.message_id)

        if not attachments:
            logger.info("[{}] No supported attachments in '{}'", client.label, email.subject)
            continue

        for att in attachments:
            row = await extractor.extract(att)

            # Delete local file immediately — data is in the row, file no longer needed
            try:
                att.local_path.unlink(missing_ok=True)
                parent = att.local_path.parent
                if parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()
                logger.debug("Deleted local file: {}", att.local_path)
            except Exception as exc:
                logger.warning("Could not delete {}: {}", att.local_path, exc)

            if row is None:
                # Breakdown or Other — skip
                continue

            if row.error:
                logger.warning("[{}] Extraction error on {} — skipping: {}", client.label, att.filename, row.error)
                continue

            logger.success(
                "[{}] {} → {} | Net: {}",
                client.label, att.filename,
                row.document_type or "?",
                row.net_amount or "?",
            )

            # ── Dedup check ────────────────────────────────────────────
            if row.invoice_number and db.is_duplicate(row.invoice_number):
                logger.warning(
                    "Duplicate invoice_number='{}' — skipping DB + Sheet write",
                    row.invoice_number,
                )
                continue

            # ── Persist ────────────────────────────────────────────────
            db.insert(row)
            sheets.append(row)
            rows_written += 1

    return rows_written


async def poll_once(
    clients: list[MailboxClient],
    extractor: OpenAIExtractor,
    sheets: SheetsWriter,
    db: SupabaseWriter,
) -> None:
    """Run one check across all mailboxes in parallel."""
    counts = await asyncio.gather(
        *[process_mailbox(c, extractor, sheets, db) for c in clients],
        return_exceptions=True,
    )
    total = 0
    for client, result in zip(clients, counts):
        if isinstance(result, Exception):
            logger.error("[{}] Poll failed: {}", client.label, result)
        else:
            total += result
    if total:
        logger.info("─── {} new row(s) written this cycle ───", total)


async def run() -> None:
    configure_logging()
    settings = get_settings()

    settings.storage_dir.mkdir(parents=True, exist_ok=True)

    all_configs = [
        ("mailbox1", settings.mailbox1()),
        ("mailbox2", settings.mailbox2()),
    ]
    clients = []
    for label, cfg in all_configs:
        if cfg.is_configured():
            clients.append(MailboxClient(label, cfg))
        else:
            logger.warning("[{}] Credentials not set — skipping", label)

    if not clients:
        logger.error("No mailboxes configured. Fill in .env and try again.")
        return

    extractor = OpenAIExtractor()
    sheets = SheetsWriter()
    db = SupabaseWriter()
    interval_seconds = POLL_INTERVAL_MINUTES * 60

    logger.info("=" * 60)
    logger.info("Invoice Automation started (polling every {} min)", POLL_INTERVAL_MINUTES)
    for c in clients:
        logger.info("  Watching  : {}", c.user)
    logger.info("  Sheet ID  : {}", settings.google_sheet_id)
    logger.info("  Supabase  : {}", settings.supabase_url)
    logger.info("  Press Ctrl+C to stop")
    logger.info("=" * 60)

    cycle = 0
    while True:
        cycle += 1
        logger.info("── Cycle #{} ──────────────────────────────────────────", cycle)
        try:
            await poll_once(clients, extractor, sheets, db)
        except Exception as exc:
            logger.error("Unexpected error in cycle {}: {}", cycle, exc)

        logger.info("Waiting {} min before next check…", POLL_INTERVAL_MINUTES)
        await asyncio.sleep(interval_seconds)


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Stopped by user (Ctrl+C)")


if __name__ == "__main__":
    main()
