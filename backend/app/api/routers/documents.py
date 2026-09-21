from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import Document, ExtractionAudit
from ...security import require_viewer

router = APIRouter(prefix="/api/documents", tags=["documents"], dependencies=[Depends(require_viewer)])


@router.get("")
def list_documents(status_filter: str | None = None, document_type: str | None = None, db: Session = Depends(get_db)):
    query = db.query(Document)
    if status_filter:
        query = query.filter(Document.processing_status == status_filter)
    if document_type:
        query = query.filter(Document.document_type == document_type)
    docs = query.order_by(Document.created_at.desc()).limit(200).all()
    return [
        {
            "document_id": d.document_id,
            "email_id": d.email_id,
            "attachment_name": d.attachment_name,
            "document_type": d.document_type.value if d.document_type else None,
            "document_number": d.document_number,
            "processing_status": d.processing_status.value,
            "extraction_confidence": d.extraction_confidence,
            "created_at": d.created_at,
        }
        for d in docs
    ]


@router.get("/{document_id}")
def get_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.document_id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    audits = db.query(ExtractionAudit).filter(ExtractionAudit.document_id == document_id).all()
    return {
        "document_id": doc.document_id,
        "email_id": doc.email_id,
        "attachment_name": doc.attachment_name,
        "document_type": doc.document_type.value if doc.document_type else None,
        "document_number": doc.document_number,
        "document_date": doc.document_date,
        "vendor": doc.vendor,
        "file_hash": doc.file_hash,
        "processing_status": doc.processing_status.value,
        "extraction_confidence": doc.extraction_confidence,
        "classification_reasons": doc.classification_reasons,
        "audit_trail": [
            {
                "stage": a.stage,
                "model": a.model,
                "overall_confidence": a.overall_confidence,
                "created_at": a.created_at,
                "raw_response": a.raw_response,
            }
            for a in audits
        ],
    }


@router.get("/{document_id}/file")
def download_document_file(document_id: str, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.document_id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return FileResponse(doc.file_location, filename=doc.attachment_name)
