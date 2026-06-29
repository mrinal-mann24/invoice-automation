from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class MailboxConfig:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str, user: str) -> None:
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.user = user

    def is_configured(self) -> bool:
        return all([self.tenant_id, self.client_id, self.client_secret, self.user])


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Mailbox 1
    mailbox1_tenant_id: str = Field(default="")
    mailbox1_client_id: str = Field(default="")
    mailbox1_client_secret: SecretStr = Field(default="")
    mailbox1_user: str = Field(default="")

    # Mailbox 2
    mailbox2_tenant_id: str = Field(default="")
    mailbox2_client_id: str = Field(default="")
    mailbox2_client_secret: SecretStr = Field(default="")
    mailbox2_user: str = Field(default="")

    # OpenAI
    openai_api_key: SecretStr = Field(default="")

    # Supabase
    supabase_url: str = Field(default="")
    supabase_key: SecretStr = Field(default="")

    # Google Sheets
    google_sheet_id: str = Field(default="")
    google_service_account_json: SecretStr = Field(default="")  # full JSON content as string

    # Config
    processed_folder_name: str = Field(default="Processed Invoices")
    log_level: str = Field(default="INFO")
    max_retries: int = Field(default=3)

    @property
    def storage_dir(self) -> Path:
        return BASE_DIR / "app" / "storage"

    @property
    def logs_dir(self) -> Path:
        return BASE_DIR / "app" / "logs"

    def mailbox1(self) -> MailboxConfig:
        return MailboxConfig(
            tenant_id=self.mailbox1_tenant_id,
            client_id=self.mailbox1_client_id,
            client_secret=self.mailbox1_client_secret.get_secret_value(),
            user=self.mailbox1_user,
        )

    def mailbox2(self) -> MailboxConfig:
        return MailboxConfig(
            tenant_id=self.mailbox2_tenant_id,
            client_id=self.mailbox2_client_id,
            client_secret=self.mailbox2_client_secret.get_secret_value(),
            user=self.mailbox2_user,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
