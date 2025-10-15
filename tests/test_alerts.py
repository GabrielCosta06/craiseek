import importlib

import config


class FakeMessages:
    def __init__(self):
        self.outbound = []

    def create(self, *, body: str, from_: str, to: str):
        self.outbound.append({"body": body, "from": from_, "to": to})


class FakeTwilioClient:
    def __init__(self):
        self.messages = FakeMessages()


def test_alerts_send_once_per_listing(app_env, monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACxxxx")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "authxxxx")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15550000000")
    config.get_settings.cache_clear()

    import db

    alerts_module = importlib.reload(importlib.import_module("alerts"))
    settings = config.get_settings()
    fake_client = FakeTwilioClient()
    service = alerts_module.AlertService(settings=settings, client=fake_client)

    db.upsert_subscriber(tier="ESSENTIAL", channels=["sms"], phone="+15555550123")
    listing = db.Listing(
        post_id="abc123",
        title="Charming Flat",
        price="$2,400",
        neighborhood="SOMA",
        url="https://example.com/listing/abc123",
    )
    db.insert_listing(listing)

    pending = db.list_unnotified_listings()
    assert len(pending) == 1

    sent = service.send_alerts(pending)
    assert sent == 1
    assert len(fake_client.messages.outbound) == 1
    assert fake_client.messages.outbound[0]["to"] == "+15555550123"
    assert "New Listing: $2,400 - Charming Flat in SOMA. Link: https://example.com/listing/abc123" in fake_client.messages.outbound[0]["body"]

    # Second run should not send duplicates because listing is marked notified.
    pending_after = db.list_unnotified_listings()
    sent_after = service.send_alerts(pending_after)
    assert sent_after == 0
    assert len(fake_client.messages.outbound) == 1
