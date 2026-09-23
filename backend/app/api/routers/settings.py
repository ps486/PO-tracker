"""Lets a non-technical user paste API keys/credentials into the dashboard
instead of editing a .env file (spec section 20/21 still apply: no password
is ever collected here, and secrets are encrypted at rest via
runtime_config.save())."""
from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...db import get_db
from ... import runtime_config
from ...security import require_admin

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_admin)])


class SettingsUpdate(BaseModel):
    gemini_api_key: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_oauth_redirect_uri: str | None = None
    gmail_query: str | None = None


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    return runtime_config.status(db)


@router.post("")
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    runtime_config.save(
        db,
        GEMINI_API_KEY=payload.gemini_api_key,
        GOOGLE_CLIENT_ID=payload.google_client_id,
        GOOGLE_CLIENT_SECRET=payload.google_client_secret,
        GOOGLE_OAUTH_REDIRECT_URI=payload.google_oauth_redirect_uri,
        GMAIL_QUERY=payload.gmail_query,
    )
    return runtime_config.status(db)
