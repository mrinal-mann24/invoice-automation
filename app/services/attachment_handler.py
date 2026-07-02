"""Downloads supported attachments (PDF + images) and saves them to disk."""
import asyncio
from pathlib import Path

from loguru import logger

from app.config.settings import get_settings
from app.graph.mail_client import MailboxClient
from app.models.models import EmailRecord, AttachmentRecord


class AttachmentHandler:
    def __init__(self, client: MailboxClient) -> None:
        self._client = client
        self._storage = get_settings().storage_dir

    async def download_for_email(self, email: EmailRecord) -> list[AttachmentRecord]:
        """List + download all supported attachments for one email."""
        save_dir = self._storage / email.mailbox_source / email.message_id
        save_dir.mkdir(parents=True, exist_ok=True)

        att_metas = await self._client.list_attachment_names(email.message_id)
        if not att_metas:
            logger.info("[{}] No supported attachments in: {}", email.mailbox_source, email.subject)
            return []

        tasks = [self._download_one(email, meta, save_dir) for meta in att_metas]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        records: list[AttachmentRecord] = []
        for meta, result in zip(att_metas, results):
            if isinstance(result, Exception):
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
        return records

    async def _download_one(
        self, email: EmailRecord, meta: dict, save_dir: Path
    ) -> AttachmentRecord:
        local_path = save_dir / meta["name"]
        if not local_path.exists() or local_path.stat().st_size == 0:
            data = await self._client.download_attachment(email.message_id, meta["id"])
            if not data:
                raise ValueError(f"Empty response downloading {meta['name']}")
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
