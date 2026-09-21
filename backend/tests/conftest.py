import os
import sys
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.app.db import Base
from backend.app import models


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def make_email(db):
    def _make(email_id="msg-1", thread_id="thread-1", subject="PO email"):
        email = models.Email(
            email_id=email_id, thread_id=thread_id, sender="Vendor Co <vendor@example.com>",
            sender_email="vendor@example.com", subject=subject, email_date=datetime.utcnow(),
            body="Please find attached.", processed_date=datetime.utcnow(),
        )
        db.add(email)
        db.flush()
        return email
    return _make


@pytest.fixture()
def make_document(db, make_email):
    def _make(email=None, file_hash="hash1", filename="po.pdf", status=models.ProcessingStatus.RECEIVED):
        email = email or make_email()
        doc = models.Document(
            email_id=email.email_id, attachment_name=filename, file_hash=file_hash,
            file_location=f"/tmp/{filename}", processing_status=status,
        )
        db.add(doc)
        db.flush()
        return doc
    return _make


@pytest.fixture()
def make_po(db):
    def _make(po_number="PO-1000", vendor_name="Acme Supplies", total_value=Decimal("11800.00"),
              po_date=date(2026, 1, 1), delivery_date=None, lines=None, status=models.POStatus.PO_RECEIVED,
              source_email_id=None):
        po = models.POMaster(
            po_number=po_number, vendor_name=vendor_name, po_date=po_date,
            delivery_date=delivery_date, total_po_value=total_value, status=status,
            source_email_id=source_email_id,
        )
        db.add(po)
        db.flush()
        for line in (lines or []):
            db.add(models.POLine(po_id=po.po_id, **line))
        db.flush()
        db.refresh(po)
        return po
    return _make
