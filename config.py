"""Application configuration management."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Application configuration loaded from environment variables."""

    database_path: str
    target_url: str
    scrape_interval_seconds: int
    request_timeout_seconds: int
    max_backoff_seconds: int
    twilio_account_sid: Optional[str]
    twilio_auth_token: Optional[str]
    twilio_from_number: Optional[str]
    twilio_whatsapp_from_number: Optional[str]
    stripe_api_key: Optional[str]
    stripe_price_id_essential: Optional[str]
    stripe_price_id_elite: Optional[str]
    stripe_webhook_secret: Optional[str]
    user_agent: str
    email_smtp_host: Optional[str]
    email_smtp_port: Optional[int]
    email_smtp_username: Optional[str]
    email_smtp_password: Optional[str]
    email_from_address: Optional[str]
    admin_api_key: Optional[str]

    @property
    def twilio_configured(self) -> bool:
        """Return True when all Twilio credentials are present."""
        return all(
            [
                self.twilio_account_sid,
                self.twilio_auth_token,
                self.twilio_from_number,
            ]
        )

    @property
    def whatsapp_configured(self) -> bool:
        """Return True if WhatsApp sending is configured."""
        return self.twilio_configured and bool(self.twilio_whatsapp_from_number)

    @property
    def email_configured(self) -> bool:
        """Return True when SMTP email credentials are present."""
        return all(
            [
                self.email_smtp_host,
                self.email_smtp_port,
                self.email_from_address,
            ]
        )

    @property
    def stripe_configured(self) -> bool:
        """Return True when Stripe credentials are present."""
        return all(
            [
                self.stripe_api_key,
                self.stripe_webhook_secret,
            ]
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings at most once per process."""
    database_path = os.getenv("DATABASE_PATH", "marketseek.db")
    target_url = os.getenv("TARGET_URL", "")
    scrape_interval = int(os.getenv("SCRAPE_INTERVAL_SECONDS", "300"))
    request_timeout = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "10"))
    max_backoff = int(os.getenv("MAX_BACKOFF_SECONDS", "120"))
    user_agent = os.getenv(
        "SCRAPER_USER_AGENT",
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36"
        ),
    )

    return Settings(
        database_path=database_path,
        target_url=target_url,
        scrape_interval_seconds=scrape_interval,
        request_timeout_seconds=request_timeout,
        max_backoff_seconds=max_backoff,
        twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID"),
        twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN"),
        twilio_from_number=os.getenv("TWILIO_FROM_NUMBER"),
        twilio_whatsapp_from_number=os.getenv("TWILIO_WHATSAPP_FROM_NUMBER"),
        stripe_api_key=os.getenv("STRIPE_API_KEY"),
        stripe_price_id_essential=os.getenv("STRIPE_PRICE_ID_ESSENTIAL"),
        stripe_price_id_elite=os.getenv("STRIPE_PRICE_ID_ELITE"),
        stripe_webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET"),
        user_agent=user_agent,
        email_smtp_host=os.getenv("EMAIL_SMTP_HOST"),
        email_smtp_port=int(os.getenv("EMAIL_SMTP_PORT", "0")) or None,
        email_smtp_username=os.getenv("EMAIL_SMTP_USERNAME"),
        email_smtp_password=os.getenv("EMAIL_SMTP_PASSWORD"),
        email_from_address=os.getenv("EMAIL_FROM_ADDRESS"),
        admin_api_key=os.getenv("ADMIN_API_KEY", "changeme"),
    )
