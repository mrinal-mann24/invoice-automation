"""Microsoft Graph mail operations for a single mailbox."""
import base64
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Optional

from azure.identity import ClientSecretCredential
from loguru import logger
from msgraph import GraphServiceClient
from msgraph.generated.models.mail_folder import MailFolder
from msgraph.generated.models.message import Message
from msgraph.generated.users.item.messages.item.move.move_post_request_body import (
    MovePostRequestBody,
)
from msgraph.generated.users.item.messages.messages_request_builder import (
    MessagesRequestBuilder,
)

from app.config.settings import MailboxConfig
from app.models.models import EmailRecord

# Attachment types we care about — skip Excel/CSV/DOCX
SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}


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
        if response.content_bytes is None:
            raise ValueError(f"No content_bytes for attachment {attachment_id}")
        return base64.b64decode(response.content_bytes)

    async def ensure_processed_folder(self, folder_name: str) -> str:
        try:
            response = await self._client.users.by_user_id(self.user).mail_folders.get()
            for folder in response.value or []:
                if folder.display_name and folder.display_name.lower() == folder_name.lower():
                    return folder.id
        except Exception as exc:
            logger.warning("[{}] Error listing folders: {}", self.label, exc)

        new_folder = MailFolder()
        new_folder.display_name = folder_name
        created = await self._client.users.by_user_id(self.user).mail_folders.post(new_folder)
        logger.info("[{}] Created folder: {}", self.label, folder_name)
        return created.id

    async def move_and_mark_read(self, message_id: str, folder_id: str) -> None:
        # Mark as read first, then move — moving changes the message ID location
        # so patching after move returns 404
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

        try:
            body = MovePostRequestBody()
            body.destination_id = folder_id
            await (
                self._client.users
                .by_user_id(self.user)
                .messages
                .by_message_id(message_id)
                .move
                .post(body)
            )
            logger.debug("[{}] Moved to Processed Invoices: {}", self.label, message_id)
        except Exception as exc:
            # 404 means the message was already moved/deleted — data is safe in Excel
            logger.warning("[{}] Could not move message (non-fatal): {}", self.label, exc)
