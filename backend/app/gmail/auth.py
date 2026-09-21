"""Gmail OAuth 2.0 flow.

No password is ever requested from the user (section 20). We use the standard
Google OAuth "web application" flow: the user is redirected to Google, grants
read-only Gmail access, Google redirects back to our callback with a code, and we
exchange it for a refresh + access token. Tokens are encrypted at rest.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from sqlalchemy.orm import Session

from ..config import settings
from ..models import OAuthToken

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _fernet() -> Fernet:
    # Derive a valid 32-byte urlsafe base64 key from SECRET_KEY so any string works.
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


def build_flow(state: str | None = None) -> Flow:
    client_config = {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.GOOGLE_OAUTH_REDIRECT_URI],
        }
    }
    return Flow.from_client_config(
        client_config, scopes=SCOPES, redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI, state=state
    )


def get_authorization_url() -> tuple[str, str]:
    flow = build_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    return auth_url, state


def exchange_code_for_tokens(db: Session, code: str, state: str, mailbox_email: str) -> OAuthToken:
    flow = build_flow(state=state)
    flow.fetch_token(code=code)
    creds = flow.credentials

    existing = (
        db.query(OAuthToken)
        .filter(OAuthToken.provider == "gmail", OAuthToken.mailbox_email == mailbox_email)
        .first()
    )
    record = existing or OAuthToken(provider="gmail", mailbox_email=mailbox_email)
    record.encrypted_refresh_token = encrypt(creds.refresh_token) if creds.refresh_token else record.encrypted_refresh_token
    record.encrypted_access_token = encrypt(creds.token) if creds.token else None
    record.token_expiry = creds.expiry
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def credentials_from_token_record(record: OAuthToken) -> Credentials:
    return Credentials(
        token=decrypt(record.encrypted_access_token) if record.encrypted_access_token else None,
        refresh_token=decrypt(record.encrypted_refresh_token),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )


def persist_refreshed_token(db: Session, record: OAuthToken, creds: Credentials) -> None:
    record.encrypted_access_token = encrypt(creds.token) if creds.token else None
    record.token_expiry = creds.expiry
    db.add(record)
    db.commit()
