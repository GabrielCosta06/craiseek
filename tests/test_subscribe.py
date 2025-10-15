import importlib

import config
from fastapi.testclient import TestClient


def test_free_plan_signup(app_env):
    config.get_settings.cache_clear()
    web = importlib.reload(importlib.import_module("web"))
    client = TestClient(web.app)

    response = client.post(
        "/subscribe/free",
        data={"email": "newuser@example.com"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("status=free")

    from db import get_all_subscribers

    subscribers = get_all_subscribers()
    assert len(subscribers) == 1
    subscriber = subscribers[0]
    assert subscriber.tier == "FREE"
    assert subscriber.email == "newuser@example.com"
    assert subscriber.channel_preferences == ["email"]

