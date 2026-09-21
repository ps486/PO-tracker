"""Thin wrapper around the Gmail API for listing messages and downloading
attachments. Kept separate from ingest.py so it can be mocked in tests without
touching any DB/parsing logic.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime

from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from ..models import OAuthToken
from . import auth as gmail_auth


@dataclass
class AttachmentRef:
    attachment_id: str
    filename: str
    mime_type: str
    size: int


@dataclass
class GmailMessage:
    message_id: str
    thread_id: str
    sender: str | None
    sender_email: str | None
    recipient: str | None
    cc: str | None
    subject: str | None
    email_date: datetime | None
    body: str
    attachments: list[AttachmentRef] = field(default_factory=list)


SUPPORTED_EXTENSIONS = {".pdf", ".xls", ".xlsx", ".csv", ".doc", ".docx", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}


class GmailClient:
    def __init__(self, db: Session, token_record: OAuthToken):
        self.db = db
        self.token_record = token_record
        creds = gmail_auth.credentials_from_token_record(token_record)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            gmail_auth.persist_refreshed_token(db, token_record, creds)
        self.service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    def list_message_ids(self, query: str, max_results: int = 50) -> list[str]:
        ids: list[str] = []
        page_token = None
        while True:
            resp = (
                self.service.users()
                .messages()
                .list(userId="me", q=query, pageToken=page_token, maxResults=min(max_results, 500))
                .execute()
            )
            ids.extend(m["id"] for m in resp.get("messages", []))
            page_token = resp.get("nextPageToken")
            if not page_token or len(ids) >= max_results:
                break
        return ids[:max_results]

    def get_message(self, message_id: str) -> GmailMessage:
        raw = self.service.users().messages().get(userId="me", id=message_id, format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in raw["payload"].get("headers", [])}

        email_date = None
        if "date" in headers:
            try:
                email_date = parsedate_to_datetime(headers["date"])
            except (ValueError, TypeError):
                email_date = None

        body = _extract_body(raw["payload"])
        attachments = _extract_attachment_refs(raw["payload"])

        sender_header = headers.get("from", "")
        sender_email = _extract_email_address(sender_header)

        return GmailMessage(
            message_id=raw["id"],
            thread_id=raw["threadId"],
            sender=sender_header or None,
            sender_email=sender_email,
            recipient=headers.get("to"),
            cc=headers.get("cc"),
            subject=headers.get("subject"),
            email_date=email_date,
            body=body,
            attachments=attachments,
        )

    def download_attachment(self, message_id: str, attachment_id: str) -> bytes:
        resp = (
            self.service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )
        return base64.urlsafe_b64decode(resp["data"])


def _extract_email_address(header_value: str) -> str | None:
    if "<" in header_value and ">" in header_value:
        return header_value.split("<", 1)[1].split(">", 1)[0].strip()
    return header_value.strip() or None


def _extract_body(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")

    for part in payload.get("parts", []) or []:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="ignore")
    for part in payload.get("parts", []) or []:
        text = _extract_body(part)
        if text:
            return text
    return ""


def _extract_attachment_refs(payload: dict, out: list[AttachmentRef] | None = None) -> list[AttachmentRef]:
    if out is None:
        out = []
    filename = payload.get("filename")
    body = payload.get("body", {})
    if filename and body.get("attachmentId"):
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext in SUPPORTED_EXTENSIONS:
            out.append(
                AttachmentRef(
                    attachment_id=body["attachmentId"],
                    filename=filename,
                    mime_type=payload.get("mimeType", "application/octet-stream"),
                    size=body.get("size", 0),
                )
            )
    for part in payload.get("parts", []) or []:
        _extract_attachment_refs(part, out)
    return out
