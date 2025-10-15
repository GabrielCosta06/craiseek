import importlib
import json

import config
from fastapi.testclient import TestClient


def test_webhook_inserts_subscriber(app_env, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test")
    monkeypatch.setenv("STRIPE_PRICE_ID_ESSENTIAL", "price_essential")
    monkeypatch.setenv("STRIPE_PRICE_ID_ELITE", "price_elite")
    config.get_settings.cache_clear()

    web = importlib.reload(importlib.import_module("web"))

    event_payload = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "customer_details": {"phone": "+15555550123", "email": "renter@example.com"},
                "metadata": {"tier": "ELITE", "channels": "sms,email,whatsapp"},
            }
        },
    }

    def fake_construct_event(payload, signature, secret):  # noqa: ARG001
        assert secret == "whsec_test"
        return event_payload

    monkeypatch.setattr(web.stripe.Webhook, "construct_event", fake_construct_event)

    client = TestClient(web.app)
    response = client.post(
        "/stripe/webhook",
        data=json.dumps(event_payload),
        headers={"stripe-signature": "test-signature", "Content-Type": "application/json"},
    )

    assert response.status_code == 200

    from db import get_all_subscribers, get_subscriber_count

    assert get_subscriber_count() == 1
    subscriber = get_all_subscribers()[0]
    assert subscriber.tier == "ELITE"
    assert set(subscriber.channel_preferences) == {"sms", "email", "whatsapp"}
    assert subscriber.email == "renter@example.com"

    # Ensure idempotency
    client.post(
        "/stripe/webhook",
        data=json.dumps(event_payload),
        headers={"stripe-signature": "test-signature", "Content-Type": "application/json"},
    )
    assert get_subscriber_count() == 1
