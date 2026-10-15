from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    secret_key: str = "troque-esta-chave"
    public_base_url: str = "http://localhost:8000"
    cors_origins: list[str] = ["http://localhost:3000"]

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/pedidos"
    redis_url: str = "redis://localhost:6379/0"

    # WhatsApp Cloud API (Meta)
    whatsapp_api_version: str = "v21.0"
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_verify_token: str = ""

    # Claude (extração). A chave vem de ANTHROPIC_API_KEY, lida pelo SDK.
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "low"
    claude_max_tokens: int = 8000

    # Whisper (transcrição). A chave vem de OPENAI_API_KEY, lida pelo SDK.
    whisper_model: str = "whisper-1"

    # Shopify
    shopify_store_domain: str = ""
    shopify_admin_token: str = ""
    shopify_webhook_secret: str = ""

    # Google Sheets
    google_service_account_file: str = ""
    google_sheets_id: str = ""
    sheets_orders_tab: str = "Pedidos"
    sheets_catalog_tab: str = "Catalogo"

    # Regras de negócio
    timezone: str = "America/Sao_Paulo"
    reminder_after_minutes: int = 10
    draft_expiry_hours: int = 24
    match_confidence_threshold: float = 0.75
    match_min_margin: float = 0.08
    # Abaixo disto o candidato não é oferecido como opção ao cliente.
    match_min_option_score: float = 0.5
    max_failed_questions: int = 2
    data_retention_days: int = 365
    privacy_policy_url: str = ""

    media_dir: str = "media"

    access_token_minutes: int = 15
    refresh_token_days: int = 7

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()
