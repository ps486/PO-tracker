"""Covers spec section 27/17: multiple attachments per email are each stored
as a separate Document, re-ingesting the same Gmail message id is a no-op, and
a re-sent identical attachment is flagged as a duplicate via file hash."""
from datetime import datetime

from backend.app import config as config_module
from backend.app.gmail import ingest
from backend.app.gmail.client import AttachmentRef, GmailMessage
from backend.app.models import Document, Email, ProcessingStatus


class FakeGmailClient:
    def __init__(self, messages: dict[str, GmailMessage], attachments: dict[str, bytes]):
        self._messages = messages
        self._attachments = attachments

    def list_message_ids(self, query, max_results=50):
        return list(self._messages.keys())[:max_results]

    def get_message(self, message_id):
        return self._messages[message_id]

    def download_attachment(self, message_id, attachment_id):
        return self._attachments[attachment_id]


def _msg(message_id, thread_id, attachments):
    return GmailMessage(
        message_id=message_id, thread_id=thread_id, sender="Vendor <v@example.com>",
        sender_email="v@example.com", recipient="us@example.com", cc=None,
        subject="PO", email_date=datetime.utcnow(), body="see attached", attachments=attachments,
    )


def test_multiple_attachments_are_stored_as_separate_documents(db, tmp_path, monkeypatch):
    monkeypatch.setattr(config_module.settings, "ATTACHMENT_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(ingest.settings, "ATTACHMENT_STORAGE_DIR", str(tmp_path))

    attachments = [AttachmentRef("att-1", "po.pdf", "application/pdf", 100),
                   AttachmentRef("att-2", "invoice.pdf", "application/pdf", 200)]
    messages = {"m1": _msg("m1", "t1", attachments)}
    blobs = {"att-1": b"pdf-content-1", "att-2": b"pdf-content-2"}
    client = FakeGmailClient(messages, blobs)

    email, docs = ingest.ingest_message(db, client, "m1")
    assert len(docs) == 2
    assert {d.attachment_name for d in docs} == {"po.pdf", "invoice.pdf"}
    assert db.query(Document).count() == 2


def test_reingesting_same_message_id_is_idempotent(db, tmp_path, monkeypatch):
    monkeypatch.setattr(config_module.settings, "ATTACHMENT_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(ingest.settings, "ATTACHMENT_STORAGE_DIR", str(tmp_path))

    attachments = [AttachmentRef("att-1", "po.pdf", "application/pdf", 100)]
    messages = {"m1": _msg("m1", "t1", attachments)}
    client = FakeGmailClient(messages, {"att-1": b"pdf-content"})

    ingest.ingest_message(db, client, "m1")
    ingest.ingest_message(db, client, "m1")

    assert db.query(Email).count() == 1
    assert db.query(Document).count() == 1


def test_resent_identical_attachment_is_flagged_duplicate(db, tmp_path, monkeypatch):
    monkeypatch.setattr(config_module.settings, "ATTACHMENT_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(ingest.settings, "ATTACHMENT_STORAGE_DIR", str(tmp_path))

    same_bytes = b"identical-pdf-bytes"
    att1 = AttachmentRef("att-1", "po.pdf", "application/pdf", 100)
    att2 = AttachmentRef("att-2", "po_forwarded.pdf", "application/pdf", 100)
    messages = {
        "m1": _msg("m1", "t1", [att1]),
        "m2": _msg("m2", "t2", [att2]),
    }
    client = FakeGmailClient(messages, {"att-1": same_bytes, "att-2": same_bytes})

    _, docs1 = ingest.ingest_message(db, client, "m1")
    _, docs2 = ingest.ingest_message(db, client, "m2")

    assert docs1[0].processing_status == ProcessingStatus.RECEIVED
    assert docs2[0].processing_status == ProcessingStatus.DUPLICATE
    assert docs1[0].file_hash == docs2[0].file_hash
