import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .db import Base


def gen_id() -> str:
    return str(uuid.uuid4())


class DocumentType(str, enum.Enum):
    PURCHASE_ORDER = "PURCHASE_ORDER"
    PO_AMENDMENT = "PO_AMENDMENT"
    ORDER_CONFIRMATION = "ORDER_CONFIRMATION"
    GRN = "GRN"
    GOODS_RECEIPT = "GOODS_RECEIPT"
    DELIVERY_CHALLAN = "DELIVERY_CHALLAN"
    TAX_INVOICE = "TAX_INVOICE"
    DEBIT_NOTE = "DEBIT_NOTE"
    CREDIT_NOTE = "CREDIT_NOTE"
    PROFORMA_INVOICE = "PROFORMA_INVOICE"
    CANCELLED_DOCUMENT = "CANCELLED_DOCUMENT"
    OTHER = "OTHER"


class ProcessingStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    PARSING = "PARSING"
    CLASSIFIED = "CLASSIFIED"
    EXTRACTED = "EXTRACTED"
    VALIDATED = "VALIDATED"
    APPLIED = "APPLIED"
    EXCEPTION = "EXCEPTION"
    DUPLICATE = "DUPLICATE"
    FAILED = "FAILED"


class POStatus(str, enum.Enum):
    PO_RECEIVED = "PO_RECEIVED"
    PO_CONFIRMED = "PO_CONFIRMED"
    PENDING_DELIVERY = "PENDING_DELIVERY"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    FULLY_RECEIVED = "FULLY_RECEIVED"
    PARTIALLY_INVOICED = "PARTIALLY_INVOICED"
    FULLY_INVOICED = "FULLY_INVOICED"
    CLOSED = "CLOSED"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"
    EXCEPTION = "EXCEPTION"
    DUPLICATE = "DUPLICATE"


class ExceptionType(str, enum.Enum):
    PO_NUMBER_MISSING = "PO_NUMBER_MISSING"
    DUPLICATE_PO = "DUPLICATE_PO"
    DUPLICATE_ATTACHMENT = "DUPLICATE_ATTACHMENT"
    GST_MISMATCH = "GST_MISMATCH"
    VENDOR_MISMATCH = "VENDOR_MISMATCH"
    PO_TOTAL_MISMATCH = "PO_TOTAL_MISMATCH"
    UNREADABLE_ATTACHMENT = "UNREADABLE_ATTACHMENT"
    UNSUPPORTED_DOCUMENT = "UNSUPPORTED_DOCUMENT"
    LOW_CLASSIFICATION_CONFIDENCE = "LOW_CLASSIFICATION_CONFIDENCE"
    LOW_FIELD_CONFIDENCE = "LOW_FIELD_CONFIDENCE"
    GRN_CANNOT_BE_MATCHED = "GRN_CANNOT_BE_MATCHED"
    INVOICE_CANNOT_BE_MATCHED = "INVOICE_CANNOT_BE_MATCHED"
    NOTE_CANNOT_BE_MATCHED = "NOTE_CANNOT_BE_MATCHED"
    MULTIPLE_POSSIBLE_PO_MATCH = "MULTIPLE_POSSIBLE_PO_MATCH"
    QUANTITY_EXCEEDS_PO_QUANTITY = "QUANTITY_EXCEEDS_PO_QUANTITY"
    INVOICE_EXCEEDS_PO_VALUE = "INVOICE_EXCEEDS_PO_VALUE"
    GRN_EXCEEDS_PO_QUANTITY = "GRN_EXCEEDS_PO_QUANTITY"
    MISSING_EXPECTED_DELIVERY_DATE = "MISSING_EXPECTED_DELIVERY_DATE"
    NEGATIVE_OR_ZERO_QUANTITY = "NEGATIVE_OR_ZERO_QUANTITY"
    ABNORMAL_TAX_RATE = "ABNORMAL_TAX_RATE"
    INVALID_GSTIN_FORMAT = "INVALID_GSTIN_FORMAT"
    MISSING_TOTAL = "MISSING_TOTAL"


class ExceptionSeverity(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ExceptionStatus(str, enum.Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RESOLVED = "RESOLVED"


class NoteType(str, enum.Enum):
    DEBIT_NOTE = "DEBIT_NOTE"
    CREDIT_NOTE = "CREDIT_NOTE"


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    FINANCE = "FINANCE"
    PROCUREMENT = "PROCUREMENT"
    VIEWER = "VIEWER"


class TimestampMixin:
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True, default=gen_id)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(UserRole, native_enum=False), default=UserRole.VIEWER, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)


class OAuthToken(Base, TimestampMixin):
    __tablename__ = "oauth_tokens"

    token_id = Column(String, primary_key=True, default=gen_id)
    provider = Column(String, default="gmail", nullable=False)
    mailbox_email = Column(String, nullable=False, index=True)
    encrypted_refresh_token = Column(Text, nullable=False)
    encrypted_access_token = Column(Text, nullable=True)
    token_expiry = Column(DateTime, nullable=True)


class AppSetting(Base, TimestampMixin):
    """Key-value store for settings that would otherwise require editing a
    .env file - lets a non-technical local user paste API keys into the
    dashboard instead of a text editor. Secret values are stored encrypted
    (same Fernet scheme as OAuthToken)."""

    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=True)
    is_secret = Column(Boolean, default=False, nullable=False)


class Vendor(Base, TimestampMixin):
    __tablename__ = "vendors"

    vendor_id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False, index=True)
    normalized_name = Column(String, nullable=False, index=True)
    gstin = Column(String, nullable=True, index=True)
    pan = Column(String, nullable=True)
    address = Column(Text, nullable=True)

    pos = relationship("POMaster", back_populates="vendor")


class Email(Base, TimestampMixin):
    __tablename__ = "emails"

    email_id = Column(String, primary_key=True)  # Gmail message id (natural key)
    thread_id = Column(String, nullable=False, index=True)
    sender = Column(String, nullable=True)
    sender_email = Column(String, nullable=True, index=True)
    recipient = Column(String, nullable=True)
    cc = Column(String, nullable=True)
    subject = Column(String, nullable=True)
    email_date = Column(DateTime, nullable=True)
    body = Column(Text, nullable=True)
    processed_date = Column(DateTime, nullable=True)

    documents = relationship("Document", back_populates="email")


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    document_id = Column(String, primary_key=True, default=gen_id)
    email_id = Column(String, ForeignKey("emails.email_id"), nullable=False, index=True)
    attachment_name = Column(String, nullable=False)
    attachment_size = Column(Integer, nullable=True)
    document_type = Column(Enum(DocumentType, native_enum=False), nullable=True)
    document_number = Column(String, nullable=True, index=True)
    document_date = Column(Date, nullable=True)
    vendor = Column(String, nullable=True)
    file_hash = Column(String, nullable=False, index=True)
    file_location = Column(String, nullable=False)
    extraction_confidence = Column(Numeric(5, 4), nullable=True)
    classification_reasons = Column(JSON, nullable=True)
    processing_status = Column(
        Enum(ProcessingStatus, native_enum=False), default=ProcessingStatus.RECEIVED, nullable=False
    )

    email = relationship("Email", back_populates="documents")
    extraction_audits = relationship("ExtractionAudit", back_populates="document")


class ExtractionAudit(Base, TimestampMixin):
    """One row per AI extraction attempt. Never overwritten - preserves history."""

    __tablename__ = "extraction_audit"

    audit_id = Column(String, primary_key=True, default=gen_id)
    document_id = Column(String, ForeignKey("documents.document_id"), nullable=False, index=True)
    stage = Column(String, nullable=False)  # classification | extraction | matching
    model = Column(String, nullable=True)
    raw_response = Column(JSON, nullable=True)
    field_confidence = Column(JSON, nullable=True)
    overall_confidence = Column(Numeric(5, 4), nullable=True)

    document = relationship("Document", back_populates="extraction_audits")


class POMaster(Base, TimestampMixin):
    __tablename__ = "po_master"

    po_id = Column(String, primary_key=True, default=gen_id)
    po_number = Column(String, nullable=False, index=True)
    po_date = Column(Date, nullable=True)
    vendor_id = Column(String, ForeignKey("vendors.vendor_id"), nullable=True)
    vendor_name = Column(String, nullable=True)
    vendor_gstin = Column(String, nullable=True)
    vendor_pan = Column(String, nullable=True)
    vendor_address = Column(Text, nullable=True)
    buyer_entity = Column(String, nullable=True)
    buyer_gstin = Column(String, nullable=True)
    ship_to = Column(Text, nullable=True)
    bill_to = Column(Text, nullable=True)
    currency = Column(String, nullable=True)
    payment_terms = Column(String, nullable=True)
    delivery_terms = Column(String, nullable=True)
    delivery_date = Column(Date, nullable=True)
    po_validity = Column(Date, nullable=True)
    buyer_reference = Column(String, nullable=True)
    vendor_reference = Column(String, nullable=True)

    gross_po_value = Column(Numeric(18, 2), nullable=True)
    taxable_value = Column(Numeric(18, 2), nullable=True)
    cgst = Column(Numeric(18, 2), nullable=True)
    sgst = Column(Numeric(18, 2), nullable=True)
    igst = Column(Numeric(18, 2), nullable=True)
    other_taxes = Column(Numeric(18, 2), nullable=True)
    freight = Column(Numeric(18, 2), nullable=True)
    discount = Column(Numeric(18, 2), nullable=True)
    other_charges = Column(Numeric(18, 2), nullable=True)
    tax_value = Column(Numeric(18, 2), nullable=True)
    total_po_value = Column(Numeric(18, 2), nullable=True)

    status = Column(Enum(POStatus, native_enum=False), default=POStatus.PO_RECEIVED, nullable=False)
    source_document_id = Column(String, ForeignKey("documents.document_id"), nullable=True)
    source_email_id = Column(String, ForeignKey("emails.email_id"), nullable=True)

    vendor = relationship("Vendor", back_populates="pos")
    lines = relationship("POLine", back_populates="po", cascade="all, delete-orphan")
    grns = relationship("GRN", back_populates="po")
    invoices = relationship("Invoice", back_populates="po")
    notes = relationship("DebitCreditNote", back_populates="po")
    source_document = relationship("Document", foreign_keys=[source_document_id])
    source_email = relationship("Email", foreign_keys=[source_email_id])


class POLine(Base, TimestampMixin):
    __tablename__ = "po_lines"

    po_line_id = Column(String, primary_key=True, default=gen_id)
    po_id = Column(String, ForeignKey("po_master.po_id"), nullable=False, index=True)
    line_number = Column(Integer, nullable=False)
    item_code = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    hsn = Column(String, nullable=True)
    quantity = Column(Numeric(18, 3), nullable=False)
    uom = Column(String, nullable=True)
    unit_price = Column(Numeric(18, 4), nullable=True)
    discount = Column(Numeric(18, 2), nullable=True)
    tax_rate = Column(Numeric(6, 3), nullable=True)
    tax_amount = Column(Numeric(18, 2), nullable=True)
    line_value = Column(Numeric(18, 2), nullable=True)
    expected_delivery_date = Column(Date, nullable=True)

    po = relationship("POMaster", back_populates="lines")
    grn_lines = relationship("GRNLine", back_populates="po_line")


class GRN(Base, TimestampMixin):
    __tablename__ = "grn"

    grn_id = Column(String, primary_key=True, default=gen_id)
    grn_number = Column(String, nullable=True, index=True)
    grn_date = Column(Date, nullable=True)
    po_id = Column(String, ForeignKey("po_master.po_id"), nullable=True, index=True)
    vendor = Column(String, nullable=True)
    received_quantity = Column(Numeric(18, 3), nullable=True)
    received_value = Column(Numeric(18, 2), nullable=True)
    warehouse_location = Column(String, nullable=True)
    source_document_id = Column(String, ForeignKey("documents.document_id"), nullable=True)

    po = relationship("POMaster", back_populates="grns")
    lines = relationship("GRNLine", back_populates="grn", cascade="all, delete-orphan")


class GRNLine(Base, TimestampMixin):
    __tablename__ = "grn_lines"

    grn_line_id = Column(String, primary_key=True, default=gen_id)
    grn_id = Column(String, ForeignKey("grn.grn_id"), nullable=False, index=True)
    po_line_id = Column(String, ForeignKey("po_lines.po_line_id"), nullable=True, index=True)
    item_code = Column(String, nullable=True)
    received_quantity = Column(Numeric(18, 3), nullable=True)
    accepted_quantity = Column(Numeric(18, 3), nullable=True)
    rejected_quantity = Column(Numeric(18, 3), nullable=True)
    value = Column(Numeric(18, 2), nullable=True)

    grn = relationship("GRN", back_populates="lines")
    po_line = relationship("POLine", back_populates="grn_lines")


class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"

    invoice_id = Column(String, primary_key=True, default=gen_id)
    invoice_number = Column(String, nullable=True, index=True)
    invoice_date = Column(Date, nullable=True)
    po_id = Column(String, ForeignKey("po_master.po_id"), nullable=True, index=True)
    grn_id = Column(String, ForeignKey("grn.grn_id"), nullable=True)
    taxable_value = Column(Numeric(18, 2), nullable=True)
    gst = Column(Numeric(18, 2), nullable=True)
    total_value = Column(Numeric(18, 2), nullable=True)
    source_document_id = Column(String, ForeignKey("documents.document_id"), nullable=True)

    po = relationship("POMaster", back_populates="invoices")


class DebitCreditNote(Base, TimestampMixin):
    __tablename__ = "debit_credit_notes"

    note_id = Column(String, primary_key=True, default=gen_id)
    note_type = Column(Enum(NoteType, native_enum=False), nullable=False)
    note_number = Column(String, nullable=True, index=True)
    note_date = Column(Date, nullable=True)
    po_id = Column(String, ForeignKey("po_master.po_id"), nullable=True, index=True)
    invoice_id = Column(String, ForeignKey("invoices.invoice_id"), nullable=True)
    reason = Column(Text, nullable=True)
    taxable_value = Column(Numeric(18, 2), nullable=True)
    gst = Column(Numeric(18, 2), nullable=True)
    total_value = Column(Numeric(18, 2), nullable=True)
    source_document_id = Column(String, ForeignKey("documents.document_id"), nullable=True)

    po = relationship("POMaster", back_populates="notes")


class ExceptionRecord(Base, TimestampMixin):
    __tablename__ = "exceptions"

    exception_id = Column(String, primary_key=True, default=gen_id)
    document_id = Column(String, ForeignKey("documents.document_id"), nullable=True, index=True)
    po_id = Column(String, ForeignKey("po_master.po_id"), nullable=True)
    exception_type = Column(Enum(ExceptionType, native_enum=False), nullable=False)
    description = Column(Text, nullable=True)
    severity = Column(Enum(ExceptionSeverity, native_enum=False), default=ExceptionSeverity.MEDIUM, nullable=False)
    status = Column(Enum(ExceptionStatus, native_enum=False), default=ExceptionStatus.OPEN, nullable=False)
    candidate_data = Column(JSON, nullable=True)  # e.g. shortlisted PO matches for review
    assigned_to = Column(String, ForeignKey("users.user_id"), nullable=True)
    resolution = Column(Text, nullable=True)
    resolved_date = Column(DateTime, nullable=True)


class AuditLog(Base, TimestampMixin):
    """Append-only log of human edits/approvals for full traceability."""

    __tablename__ = "audit_log"

    log_id = Column(String, primary_key=True, default=gen_id)
    entity_type = Column(String, nullable=False)  # e.g. "po_master", "exceptions"
    entity_id = Column(String, nullable=False, index=True)
    field = Column(String, nullable=True)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    action = Column(String, nullable=False)  # CREATE | UPDATE | APPROVE | REJECT
    user_id = Column(String, ForeignKey("users.user_id"), nullable=True)
