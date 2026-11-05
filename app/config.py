import re
from functools import lru_cache
from typing import Optional
from zoneinfo import ZoneInfo
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENVIRONMENT: str = "development"
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    PUBLIC_HOST: str = "localhost:8000"
    API_KEY: str = "visitsly_secret_booking_key_2026"
    ADMIN_API_KEY: str = "visitsly_admin_secret_key_2026"
    COMPANY_NAME: str = "Visitsly"
    TIMEZONE: str = "Asia/Kolkata"

    DATABASE_URL: str = "sqlite+aiosqlite:///./voice_agent.db"

    # Plivo
    PLIVO_AUTH_ID: str = ""
    PLIVO_AUTH_TOKEN: str = ""
    PLIVO_CALLER_ID: str = "+918047289335"
    PLIVO_CPS: float = 1.0
    PLIVO_ANSWER_METHOD: str = "POST"
    PLIVO_HANGUP_METHOD: str = "POST"
    PLIVO_MACHINE_DETECTION: str = "none"  # "none" | "hangup" | "true"

    # Calling policies
    CALLING_WINDOW_START_HOUR: int = 9
    CALLING_WINDOW_END_HOUR: int = 21
    MAX_RETRY_ATTEMPTS: int = 2
    RETRY_MIN_INTERVAL_HOURS: int = 2
    MAX_CALL_DURATION_SECONDS: int = 180
    SILENCE_TIMEOUT_SECONDS: float = 6.0
    MAX_SILENCE_PROMPTS: int = 2

    # SaaS Webhook
    SAAS_WEBHOOK_URL: str = "http://localhost:3000/api/webhooks/voice/test"
    SAAS_WEBHOOK_SECRET: str = "visitsly_webhook_hmac_secret_key_32chars"

    # Providers
    LLM_PROVIDER: str = "groq"  # groq | claude | gemini | mock
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "qwen/qwen3.8-27b"

    ANTHROPIC_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-3-5-sonnet-20241022"

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-flash"

    STT_PROVIDER: str = "deepgram"  # deepgram | groq | sarvam | mock
    DEEPGRAM_API_KEY: str = ""
    DEEPGRAM_MODEL: str = "nova-2"
    DEEPGRAM_LANGUAGE: str = "hi"
    SARVAM_API_KEY: str = ""

    TTS_PROVIDER: str = "edge_tts"  # edge_tts | sarvam | elevenlabs | mock
    EDGE_TTS_VOICE: str = "hi-IN-SwaraNeural"
    SARVAM_TTS_VOICE: str = "meera"

    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = "cgSgspJ2msm6clMCkdW9"
    ELEVENLABS_MODEL: str = "eleven_flash_v2_5"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.TIMEZONE)

    @property
    def stream_ws_url(self) -> str:
        clean_host = self.PUBLIC_HOST.strip().rstrip("/")
        # If public host has scheme, strip it
        clean_host = re.sub(r"^https?://", "", clean_host)
        clean_host = re.sub(r"^wss?://", "", clean_host)
        return f"wss://{clean_host}/plivo/stream"

    @property
    def webhook_base_url(self) -> str:
        clean_host = self.PUBLIC_HOST.strip().rstrip("/")
        clean_host = re.sub(r"^https?://", "", clean_host)
        clean_host = re.sub(r"^wss?://", "", clean_host)
        scheme = "https" if "localhost" not in clean_host else "http"
        return f"{scheme}://{clean_host}"


def get_settings() -> Settings:
    """Always loads fresh settings from .env so configuration updates take effect immediately."""
    return Settings(_env_file=".env", _env_file_encoding="utf-8")


def mask_phone(phone: str) -> str:
    """Masks customer phone number for compliance (e.g., +91 98**** 1234)."""
    if not phone or len(phone) < 7:
        return "****"
    cleaned = re.sub(r"\s+", "", phone)
    prefix = cleaned[:5]
    suffix = cleaned[-4:]
    return f"{prefix}****{suffix}"
