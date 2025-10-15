from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Optional, Sequence

try:
    from twilio.base.exceptions import TwilioRestException
    from twilio.rest import Client
    TWILIO_AVAILABLE = True
except ImportError:  # pragma: no cover - allow tests without Twilio installed
    TwilioRestException = Exception  # type: ignore[assignment]

    class Client:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs) -> None:  # noqa: D401 - dummy client
            raise RuntimeError(
                "Twilio SDK is not installed. Install dependencies with `pip install -r requirements.txt`."
            )

    TWILIO_AVAILABLE = False

from config import Settings, get_settings
from db import Listing, Subscriber, get_all_subscribers, mark_listings_notified

logger = logging.getLogger(__name__)


def _format_message(listing: Listing) -> str:
    """Format an outbound SMS for a listing."""
    parts = ["New Listing:"]
    if listing.price:
        parts.append(f"{listing.price}")
    if listing.title:
        if listing.price:
            parts.append(f"- {listing.title}")
        else:
            parts.append(listing.title)
    if listing.neighborhood:
        parts.append(f"in {listing.neighborhood}")
    message = " ".join(parts).strip()
    message = f"{message}. Link: {listing.url}"
    return message


class AlertService:
    """Send SMS alerts via Twilio."""

    def __init__(self, settings: Optional[Settings] = None, client: Optional[Client] = None) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._email_service = EmailService(self.settings) if self.settings.email_configured else None

    @property
    def client(self) -> Optional[Client]:
        if self._client is None and self.settings.twilio_configured:
            if not TWILIO_AVAILABLE:
                logger.error("Twilio SDK not installed; cannot send alerts.")
                return None
            self._client = Client(
                self.settings.twilio_account_sid,
                self.settings.twilio_auth_token,
            )
        return self._client

    def send_alerts(self, listings: Sequence[Listing]) -> int:
        """Send alerts for listings and return count of notified listings."""
        if not listings:
            return 0

        subscribers = get_all_subscribers()
        if not subscribers:
            logger.info("No subscribers; skipping alerts.")
            return 0

        twilio_client = self.client if self.settings.twilio_configured else None
        if twilio_client is None and any(
            {"sms", "whatsapp"}.intersection(sub.channel_preferences) for sub in subscribers
        ):
            logger.warning("Twilio credentials missing; SMS/WhatsApp alerts will be skipped.")

        notified_post_ids: list[str] = []
        for listing in listings:
            body = _format_message(listing)
            logger.info(
                "Sending alerts for listing",
                extra={"post_id": listing.post_id, "subscriber_count": len(subscribers)},
            )
            delivered_any = False
            for subscriber in subscribers:
                delivered_to_subscriber = False
                for channel in subscriber.channel_preferences:
                    channel = channel.lower()
                    if channel == "sms":
                        if not (twilio_client and subscriber.phone):
                            continue
                        try:
                            twilio_client.messages.create(
                                body=body,
                                from_=self.settings.twilio_from_number,
                                to=subscriber.phone,
                            )
                            delivered_to_subscriber = True
                        except TwilioRestException as exc:
                            logger.error(
                                "Failed SMS alert",
                                extra={"post_id": listing.post_id, "phone": subscriber.phone, "error": str(exc)},
                            )
                        except Exception as exc:  # pragma: no cover - defensive logging
                            logger.exception(
                                "Unexpected SMS error",
                                extra={"post_id": listing.post_id, "phone": subscriber.phone, "error": str(exc)},
                            )
                    elif channel == "whatsapp":
                        if not (twilio_client and self.settings.whatsapp_configured):
                            continue
                        destination = subscriber.whatsapp or subscriber.phone
                        if not destination:
                            continue
                        to_number = destination if destination.startswith("whatsapp:") else f"whatsapp:{destination}"
                        from_number = self.settings.twilio_whatsapp_from_number
                        try:
                            twilio_client.messages.create(
                                body=body,
                                from_=from_number,
                                to=to_number,
                            )
                            delivered_to_subscriber = True
                        except TwilioRestException as exc:
                            logger.error(
                                "Failed WhatsApp alert",
                                extra={"post_id": listing.post_id, "phone": destination, "error": str(exc)},
                            )
                        except Exception as exc:  # pragma: no cover
                            logger.exception(
                                "Unexpected WhatsApp error",
                                extra={"post_id": listing.post_id, "phone": destination, "error": str(exc)},
                            )
                    elif channel == "email":
                        if not (self._email_service and subscriber.email):
                            continue
                        try:
                            self._email_service.send_listing_email(subscriber.email, listing, body)
                            delivered_to_subscriber = True
                        except Exception as exc:  # pragma: no cover - defensive logging
                            logger.exception(
                                "Unexpected email error",
                                extra={"post_id": listing.post_id, "email": subscriber.email, "error": str(exc)},
                            )
                if delivered_to_subscriber:
                    delivered_any = True
            if delivered_any:
                notified_post_ids.append(listing.post_id)
            else:
                logger.error(
                    "Failed to deliver listing alert to any subscriber",
                    extra={"post_id": listing.post_id},
                )

        if notified_post_ids:
            mark_listings_notified(notified_post_ids)
        return len(notified_post_ids)


class EmailService:
    """Simple SMTP email sender."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _connect(self) -> smtplib.SMTP:
        if not self.settings.email_smtp_host:
            raise RuntimeError("Email SMTP host not configured.")
        port = self.settings.email_smtp_port or 587
        if port == 465:
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(self.settings.email_smtp_host, port)
        else:
            smtp = smtplib.SMTP(self.settings.email_smtp_host, port)
            smtp.starttls()
        if self.settings.email_smtp_username and self.settings.email_smtp_password:
            smtp.login(self.settings.email_smtp_username, self.settings.email_smtp_password)
        return smtp

    def send_listing_email(self, to_email: str, listing: Listing, body: str) -> None:
        if not self.settings.email_from_address:
            raise RuntimeError("EMAIL_FROM_ADDRESS must be configured for email alerts.")
        subject = f"New Rental Alert: {listing.title}"
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.settings.email_from_address
        msg["To"] = to_email
        msg.set_content(f"{body}\n\nSent via Craiseek rental radar.")

        with self._connect() as smtp:
            smtp.send_message(msg)


__all__ = ["AlertService", "_format_message", "EmailService"]
