import importlib

import config
from fastapi.testclient import TestClient


def test_register_login_dashboard_flow(app_env):
    config.get_settings.cache_clear()
    web = importlib.reload(importlib.import_module("web"))

    client = TestClient(web.app)

    response = client.post(
        "/register",
        data={"email": "User@example.com", "password": "supersecret"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"

    dashboard = client.get("/dashboard", follow_redirects=False)
    assert dashboard.status_code == 200
    assert "Latest Rentals" in dashboard.text

    logout = client.post("/logout", follow_redirects=False)
    assert logout.status_code == 303
    assert logout.headers["location"] == "/"

    unauthorized = client.get("/dashboard", follow_redirects=False)
    assert unauthorized.status_code == 303
    assert unauthorized.headers["location"] == "/login"

    login = client.post(
        "/login",
        data={"email": "user@example.com", "password": "supersecret"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert login.headers["location"] == "/dashboard"

