"""Microsoft Graph mail operations for a single mailbox."""
import base64
import re
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Optional

from azure.identity import ClientSecretCredential
from loguru import logger
from msgraph import GraphServiceClient
from msgraph.generated.models.message import Message
from msgraph.generated.users.item.messages.messages_request_builder import (
    MessagesRequestBuilder,
)

from app.config.settings import MailboxConfig
from app.models.models import EmailRecord

# Attachment types we care about — skip Excel/CSV/DOCX
SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}

# Only real file attachments carry downloadable contentBytes. itemAttachment
# (an attached email/event) and referenceAttachment (a OneDrive/SharePoint link)
# have no file bytes — trying to download them yields non-PDF junk that PyMuPDF
# then fails to open ("Failed to open file as type pdf").
FILE_ATTACHMENT_ODATA_TYPE = "#microsoft.graph.fileAttachment"

# Graph autogenerates names like "ATT00001.jpg" for images that were inline in
# the email body (signature logos, tracking pixels, header banners) but which it
# fails to flag isInline=true — common on forwarded mail. These are never the
# actual invoice; sending them to GPT just wastes calls and errors out.
_INLINE_NAME_RE = re.compile(r"^ATT\d+\.\w+$", re.IGNORECASE)


def build_client(cfg: MailboxConfig) -> GraphServiceClient:
    credential = ClientSecretCredential(
        tenant_id=cfg.tenant_id,
        client_id=cfg.client_id,
        client_secret=cfg.client_secret,
    )
    return GraphServiceClient(credentials=credential, scopes=["https://graph.microsoft.com/.default"])


class MailboxClient:
    def __init__(self, label: str, cfg: MailboxConfig) -> None:
        self.label = label
        self.user = cfg.user
        self._client = build_client(cfg)

    async def fetch_todays_unread_emails(self) -> list[EmailRecord]:
        today = date.today().isoformat()
        filter_query = (
            f"receivedDateTime ge {today}T00:00:00Z "
            f"and receivedDateTime lt {today}T23:59:59Z "
            f"and isRead eq false"
        )

        try:
            query_params = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
                filter=filter_query,
                select=["id", "subject", "from", "receivedDateTime", "isRead"],
                top=100,
            )
            request_config = MessagesRequestBuilder.MessagesRequestBuilderGetRequestConfiguration(
                query_parameters=query_params,
            )
            response = await (
                self._client.users
                .by_user_id(self.user)
                .messages
                .get(request_configuration=request_config)
            )
        except Exception as exc:
            logger.error("[{}] Failed to fetch emails: {}", self.label, exc)
            raise

        records: list[EmailRecord] = []
        for msg in response.value or []:
            records.append(EmailRecord(
                message_id=msg.id,
                subject=msg.subject or "(no subject)",
                sender=(
                    msg.from_.email_address.address
                    if msg.from_ and msg.from_.email_address else ""
                ),
                received_datetime=msg.received_date_time or datetime.now(timezone.utc),
                mailbox_source=self.label,
            ))

        logger.info("[{}] {} unread emails today", self.label, len(records))
        return records

    async def list_attachment_names(self, message_id: str) -> list[dict]:
        """Returns list of {id, name, content_type, size} for supported attachments only."""
        try:
            response = await (
                self._client.users
                .by_user_id(self.user)
                .messages
                .by_message_id(message_id)
                .attachments
                .get()
            )
        except Exception as exc:
            logger.warning("[{}] Could not list attachments for {}: {}", self.label, message_id, exc)
            return []

        result = []
        for att in response.value or []:
            if getattr(att, "is_inline", False):
                logger.debug("[{}] Skipping inline image: {}", self.label, att.name)
                continue
            if att.name and _INLINE_NAME_RE.match(att.name):
                logger.info("[{}] Skipping inline-style attachment: {}", self.label, att.name)
                continue
            odata_type = getattr(att, "odata_type", None)
            if odata_type != FILE_ATTACHMENT_ODATA_TYPE:
                # itemAttachment / referenceAttachment have no downloadable file bytes
                logger.info(
                    "[{}] Skipping non-file attachment ({}): {}",
                    self.label, odata_type or "unknown type", att.name,
                )
                continue
            if not getattr(att, "size", 1) or att.size == 0:
                logger.debug("[{}] Skipping zero-size attachment: {}", self.label, att.name)
                continue
            ext = Path(att.name or "").suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                logger.debug("[{}] Skipping unsupported attachment: {}", self.label, att.name)
                continue
            result.append({
                "id": att.id,
                "name": att.name or "unknown",
                "content_type": att.content_type or "application/octet-stream",
                "size": att.size or 0,
            })
        return result

    async def download_attachment(self, message_id: str, attachment_id: str) -> bytes:
        response = await (
            self._client.users
            .by_user_id(self.user)
            .messages
            .by_message_id(message_id)
            .attachments
            .by_attachment_id(attachment_id)
            .get()
        )
        content_bytes = getattr(response, "content_bytes", None)
        if content_bytes is None:
            raise ValueError(f"No content_bytes for attachment {attachment_id}")
        return base64.b64decode(content_bytes)

    async def mark_read(self, message_id: str) -> None:
        # Stays in the Inbox — just flip isRead so it isn't picked up again next cycle
        try:
            patch = Message()
            patch.is_read = True
            await (
                self._client.users
                .by_user_id(self.user)
                .messages
                .by_message_id(message_id)
                .patch(patch)
            )
        except Exception as exc:
            logger.warning("[{}] Could not mark as read (non-fatal): {}", self.label, exc)
