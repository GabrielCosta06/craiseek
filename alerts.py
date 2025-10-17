"""Alert service for sending notifications via SMS, WhatsApp, and email."""
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
        """Dummy Twilio client for when SDK is not installed."""
        def __init__(self, *args, **kwargs) -> None:
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
    """Send alerts via multiple channels: SMS, WhatsApp, and email."""

    def __init__(self, settings: Optional[Settings] = None, client: Optional[Client] = None) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._email_service = EmailService(self.settings) if self.settings.email_configured else None

    @property
    def client(self) -> Optional[Client]:
        """Get or create Twilio client if configured."""
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
        """
        Send alerts for new listings to all subscribers.
        
        Returns:
            Number of listings successfully notified to at least one subscriber.
        """
        if not listings:
            return 0

        subscribers = get_all_subscribers()
        if not subscribers:
            logger.info("No subscribers; skipping alerts.")
            return 0

        twilio_client = self.client if self.settings.twilio_configured else None
        self._warn_if_missing_credentials(subscribers, twilio_client)

        notified_post_ids: list[str] = []
        for listing in listings:
            if self._send_listing_alerts(listing, subscribers, twilio_client):
                notified_post_ids.append(listing.post_id)

        if notified_post_ids:
            mark_listings_notified(notified_post_ids)
        
        return len(notified_post_ids)

    def _warn_if_missing_credentials(
        self, 
        subscribers: Sequence[Subscriber], 
        twilio_client: Optional[Client]
    ) -> None:
        """Warn if subscribers need SMS/WhatsApp but Twilio is not configured."""
        if twilio_client is None:
            needs_twilio = any(
                {"sms", "whatsapp"}.intersection(sub.channel_preferences) 
                for sub in subscribers
            )
            if needs_twilio:
                logger.warning("Twilio credentials missing; SMS/WhatsApp alerts will be skipped.")

    def _send_listing_alerts(
        self,
        listing: Listing,
        subscribers: Sequence[Subscriber],
        twilio_client: Optional[Client]
    ) -> bool:
        """
        Send alert for a single listing to all subscribers.
        
        Returns:
            True if at least one subscriber was successfully notified.
        """
        message_body = _format_message(listing)
        logger.info(
            "Sending alerts for listing",
            extra={"post_id": listing.post_id, "subscriber_count": len(subscribers)},
        )
        
        delivered_to_any = False
        for subscriber in subscribers:
            if self._send_to_subscriber(listing, subscriber, message_body, twilio_client):
                delivered_to_any = True

        if not delivered_to_any:
            logger.error(
                "Failed to deliver listing alert to any subscriber",
                extra={"post_id": listing.post_id},
            )
        
        return delivered_to_any

    def _send_to_subscriber(
        self,
        listing: Listing,
        subscriber: Subscriber,
        message_body: str,
        twilio_client: Optional[Client]
    ) -> bool:
        """
        Send alert to a single subscriber via all their preferred channels.
        
        Returns:
            True if delivery succeeded on at least one channel.
        """
        delivered = False
        for channel in subscriber.channel_preferences:
            channel_lower = channel.lower()
            
            if channel_lower == "sms":
                delivered |= self._send_sms(listing, subscriber, message_body, twilio_client)
            elif channel_lower == "whatsapp":
                delivered |= self._send_whatsapp(listing, subscriber, message_body, twilio_client)
            elif channel_lower == "email":
                delivered |= self._send_email(listing, subscriber, message_body)
        
        return delivered

    def _send_sms(
        self,
        listing: Listing,
        subscriber: Subscriber,
        message_body: str,
        twilio_client: Optional[Client]
    ) -> bool:
        """Send SMS alert to subscriber."""
        if not (twilio_client and subscriber.phone):
            return False
        
        try:
            twilio_client.messages.create(
                body=message_body,
                from_=self.settings.twilio_from_number,
                to=subscriber.phone,
            )
            return True
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
        return False

    def _send_whatsapp(
        self,
        listing: Listing,
        subscriber: Subscriber,
        message_body: str,
        twilio_client: Optional[Client]
    ) -> bool:
        """Send WhatsApp alert to subscriber."""
        if not (twilio_client and self.settings.whatsapp_configured):
            return False
        
        destination = subscriber.whatsapp or subscriber.phone
        if not destination:
            return False
        
        to_number = destination if destination.startswith("whatsapp:") else f"whatsapp:{destination}"
        from_number = self.settings.twilio_whatsapp_from_number
        
        try:
            twilio_client.messages.create(
                body=message_body,
                from_=from_number,
                to=to_number,
            )
            return True
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
        return False

    def _send_email(
        self,
        listing: Listing,
        subscriber: Subscriber,
        message_body: str
    ) -> bool:
        """Send email alert to subscriber."""
        if not (self._email_service and subscriber.email):
            return False
        
        try:
            self._email_service.send_listing_email(subscriber.email, listing, message_body)
            return True
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception(
                "Unexpected email error",
                extra={"post_id": listing.post_id, "email": subscriber.email, "error": str(exc)},
            )
        return False


class EmailService:
    """Simple SMTP email sender for listing alerts."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send_listing_email(self, to_email: str, listing: Listing, body: str) -> None:
        """Send email notification about a new listing."""
        if not self.settings.email_from_address:
            raise RuntimeError("EMAIL_FROM_ADDRESS must be configured for email alerts.")
        
        subject = f"New Rental Alert: {listing.title}"
        msg = self._create_message(to_email, subject, body)
        
        with self._connect() as smtp:
            smtp.send_message(msg)

    def _create_message(self, to_email: str, subject: str, body: str) -> EmailMessage:
        """Create an email message with proper headers."""
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.settings.email_from_address
        msg["To"] = to_email
        msg.set_content(f"{body}\n\nSent via Craiseek rental radar.")
        return msg

    def _connect(self) -> smtplib.SMTP:
        """Establish SMTP connection with TLS support."""
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


__all__ = ["AlertService", "_format_message", "EmailService"]
