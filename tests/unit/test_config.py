"""Real gap found during the pre-deployment audit (2026-08-04): app/config.py's
jwt_secret_key silently defaulted to "" if JWT_SECRET_KEY was ever unset —
jose.jwt would happily sign/verify every session cookie with an empty key,
letting anyone forge a valid session. The app must refuse to start instead."""

import importlib

import pytest


def test_settings_refuses_to_start_with_no_jwt_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    # config.py calls load_dotenv() on import/reload, which would otherwise
    # re-populate JWT_SECRET_KEY right back out of the real .env file.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)
    import app.config as config_module

    try:
        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
            importlib.reload(config_module)
    finally:
        # restore the real module state for every test after this one
        monkeypatch.undo()
        importlib.reload(config_module)
