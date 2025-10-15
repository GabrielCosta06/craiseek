import importlib
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402


def _reload_module(name: str):
    if name in sys.modules:
        return importlib.reload(sys.modules[name])
    return importlib.import_module(name)


@pytest.fixture
def app_env(tmp_path, monkeypatch) -> Iterator[None]:
    """Reset environment for each test with an isolated database."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("TARGET_URL", "https://example.com/target")
    config.get_settings.cache_clear()

    _reload_module("db")
    _reload_module("alerts")
    yield

