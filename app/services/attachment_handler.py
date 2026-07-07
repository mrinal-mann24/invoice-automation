"""Downloads supported attachments (PDF + images) and saves them to disk."""
import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from app.config.settings import get_settings
from app.graph.mail_client import MailboxClient
from app.models.models import EmailRecord, AttachmentRecord


@dataclass
class DownloadResult:
    """Outcome of downloading one email's attachments.

    had_failures lets the caller keep the email UNREAD when a download failed, so
    it is retried on a later cycle instead of being silently dropped.
    """

    records: list[AttachmentRecord] = field(default_factory=list)
    had_failures: bool = False


class AttachmentHandler:
    def __init__(self, client: MailboxClient) -> None:
        self._client = client
        self._storage = get_settings().storage_dir

    async def download_for_email(self, email: EmailRecord) -> "DownloadResult":
        """List + download all supported attachments for one email.

        Returns a DownloadResult carrying the successfully-downloaded records plus
        flags describing what failed, so the caller can decide whether it is safe
        to mark the email as read (only when nothing failed).
        """
        save_dir = self._storage / email.mailbox_source / email.message_id
        save_dir.mkdir(parents=True, exist_ok=True)

        att_metas = await self._client.list_attachment_names(email.message_id)
        if not att_metas:
            logger.info("[{}] No supported attachments in: {}", email.mailbox_source, email.subject)
            return DownloadResult(records=[], had_failures=False)

        tasks = [self._download_one(email, meta, save_dir) for meta in att_metas]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        records: list[AttachmentRecord] = []
        had_failures = False
        for meta, result in zip(att_metas, results):
            if isinstance(result, Exception):
                had_failures = True
                logger.error(
                    "[{}] Failed to download {}: {}",
                    email.mailbox_source, meta["name"], result,
                )
            else:
                records.append(result)

        logger.info(
            "[{}] Downloaded {}/{} attachments from '{}'",
            email.mailbox_source, len(records), len(att_metas), email.subject,
        )
        return DownloadResult(records=records, had_failures=had_failures)

    async def _download_one(
        self, email: EmailRecord, meta: dict, save_dir: Path
    ) -> AttachmentRecord:
        local_path = save_dir / meta["name"]
        if not local_path.exists() or local_path.stat().st_size == 0:
            data = await self._client.download_attachment(email.message_id, meta["id"])
            if not data:
                raise ValueError(f"Empty response downloading {meta['name']}")
            _verify_bytes(meta["name"], data)
            local_path.write_bytes(data)
            logger.debug(
                "[{}] Saved {} ({} bytes)",
                email.mailbox_source, meta["name"], len(data),
            )
        return AttachmentRecord(
            message_id=email.message_id,
            mailbox_source=email.mailbox_source,
            subject=email.subject,
            sender=email.sender,
            received_datetime=email.received_datetime,
            filename=meta["name"],
            local_path=local_path,
            content_type=meta["content_type"],
        )


class CorruptDownloadError(ValueError):
    """Downloaded attachment bytes are not a valid file.

    Kept distinct from other errors so the caller can leave the email UNREAD for
    automatic retry instead of silently dropping it.
    """


# The tell-tale signature of a DOUBLE base64-decode: a real PDF header ("%PDF")
# run through base64.b64decode a second time always begins with these bytes.
# If this ever fires again it means content_bytes was decoded twice — check
# download_attachment() in mail_client.py, not an encryption policy.
_DOUBLE_DECODED_PDF_PREFIX = b"<1u"


def _verify_bytes(name: str, data: bytes) -> None:
    """
    Reject downloads whose bytes don't match their extension *before* they land
    on disk. A bad file that gets written would be cached (the exists() guard
    skips re-download) and fail extraction every single cycle. Raising here means
    nothing is written and the next cycle retries cleanly.
    """
    if data.startswith(_DOUBLE_DECODED_PDF_PREFIX):
        preview = data[:16]
        raise CorruptDownloadError(
            f"{name} looks DOUBLE base64-decoded (magic bytes: {preview!r}). "
            "content_bytes was decoded twice — check download_attachment() in "
            "mail_client.py. Left unread for retry."
        )

    if Path(name).suffix.lower() == ".pdf" and not data.startswith(b"%PDF"):
        preview = data[:16]
        raise ValueError(
            f"{name} is not a valid PDF (magic bytes: {preview!r}) — "
            "likely a reference/item attachment or a corrupt download"
        )
