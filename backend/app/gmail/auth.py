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
from googleapiclient.discovery import build

from sqlalchemy.orm import Session

from .. import runtime_config
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
            "client_id": runtime_config.GOOGLE_CLIENT_ID,
            "client_secret": runtime_config.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [runtime_config.GOOGLE_OAUTH_REDIRECT_URI],
        }
    }
    # get_authorization_url() and exchange_code_for_tokens() each build their
    # own Flow instance (they run in separate HTTP requests, potentially
    # minutes apart) - the library's default auto-generated PKCE code
    # verifier lives only on the Flow instance that created it, so the second
    # Flow never has the matching verifier and Google rejects the token
    # exchange with "invalid_grant: Missing code verifier". This is a
    # confidential client (it has a client secret, unlike a public
    # mobile/SPA client), so PKCE isn't required for security here -
    # disabling it avoids the mismatch entirely instead of needing to
    # persist the verifier between requests.
    return Flow.from_client_config(
        client_config, scopes=SCOPES, redirect_uri=runtime_config.GOOGLE_OAUTH_REDIRECT_URI, state=state,
        autogenerate_code_verifier=False,
    )


def get_authorization_url() -> tuple[str, str]:
    flow = build_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    return auth_url, state


def _discover_mailbox_email(creds: Credentials) -> str:
    """Google's OAuth redirect never tells us which mailbox was granted - we
    have to ask Gmail itself, using the credentials we just received. This
    also guarantees the stored mailbox_email is the one the user actually
    consented with, not whatever a caller happened to pass in."""
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    return profile["emailAddress"]


def exchange_code_for_tokens(db: Session, code: str, state: str) -> OAuthToken:
    flow = build_flow(state=state)
    flow.fetch_token(code=code)
    creds = flow.credentials
    mailbox_email = _discover_mailbox_email(creds)

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
        client_id=runtime_config.GOOGLE_CLIENT_ID,
        client_secret=runtime_config.GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )


def persist_refreshed_token(db: Session, record: OAuthToken, creds: Credentials) -> None:
    record.encrypted_access_token = encrypt(creds.token) if creds.token else None
    record.token_expiry = creds.expiry
    db.add(record)
    db.commit()
