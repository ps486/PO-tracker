"""Mutable runtime settings.

`config.settings` (pydantic BaseSettings) is read once from environment
variables at process start and never changes - that's fine for a server
deployment where an operator edits `.env` and restarts. It's not fine for a
non-technical local user, who has no way to edit `.env` or restart a process.

This module holds the *effective* values the rest of the app should use: it
starts from `config.settings`, then `load_from_db()` (called once at startup)
overrides anything saved via the Settings screen, and `save()` (called by the
Settings API) updates both the database and these in-memory values
immediately - no restart required.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .config import settings

ANTHROPIC_API_KEY = settings.ANTHROPIC_API_KEY
AI_MODEL = settings.AI_MODEL
GOOGLE_CLIENT_ID = settings.GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET = settings.GOOGLE_CLIENT_SECRET
GOOGLE_OAUTH_REDIRECT_URI = settings.GOOGLE_OAUTH_REDIRECT_URI
GMAIL_QUERY = settings.GMAIL_QUERY

_SECRET_KEYS = {"ANTHROPIC_API_KEY", "GOOGLE_CLIENT_SECRET"}
_ALL_KEYS = {"ANTHROPIC_API_KEY", "AI_MODEL", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
             "GOOGLE_OAUTH_REDIRECT_URI", "GMAIL_QUERY"}


def _encrypt(value: str) -> str:
    from .gmail.auth import encrypt
    return encrypt(value)


def _decrypt(value: str) -> str:
    from .gmail.auth import decrypt
    return decrypt(value)


def load_from_db(db: Session) -> None:
    """Called once at app startup - pulls any previously-saved settings over
    the environment-variable defaults."""
    from .models import AppSetting

    for row in db.query(AppSetting).all():
        if row.key not in _ALL_KEYS:
            continue
        value = _decrypt(row.value) if row.is_secret and row.value else row.value
        globals()[row.key] = value


def save(db: Session, **updates: str) -> None:
    """Saves the given settings (only keys with a non-empty value are
    touched, so re-saving the form without retyping a secret doesn't blank
    it out) and applies them immediately in this process."""
    from .models import AppSetting

    for key, value in updates.items():
        if key not in _ALL_KEYS or not value:
            continue
        is_secret = key in _SECRET_KEYS
        stored_value = _encrypt(value) if is_secret else value
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row is None:
            row = AppSetting(key=key, is_secret=is_secret)
        row.value = stored_value
        row.is_secret = is_secret
        db.add(row)
        globals()[key] = value
    db.commit()


def status(db: Session) -> dict:
    """What the Settings screen shows: whether each secret is configured
    (never the value itself), plus the current non-secret values."""
    return {
        "anthropic_api_key_set": bool(ANTHROPIC_API_KEY),
        "google_client_id": GOOGLE_CLIENT_ID,  # not a secret - fine to show as-is
        "google_client_id_set": bool(GOOGLE_CLIENT_ID),
        "google_client_secret_set": bool(GOOGLE_CLIENT_SECRET),
        "google_oauth_redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
        "gmail_query": GMAIL_QUERY,
        "ai_model": AI_MODEL,
    }
