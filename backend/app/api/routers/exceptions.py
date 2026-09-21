"""Exception queue (spec sections 13-14): view, correct, approve/reject.
Every action is written to AUDIT_LOG so corrections are never silently applied
without a trace back to who did what and when.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import AuditLog, ExceptionRecord, ExceptionStatus, POMaster, User
from ...schemas import ExceptionOut, ExceptionResolveRequest
from ...security import require_procurement, require_viewer
from ...status.po_status import apply_metrics, compute_po_metrics

router = APIRouter(prefix="/api/exceptions", tags=["exceptions"])


@router.get("", response_model=list[ExceptionOut], dependencies=[Depends(require_viewer)])
def list_exceptions(status_filter: str | None = None, severity: str | None = None, db: Session = Depends(get_db)):
    query = db.query(ExceptionRecord)
    if status_filter:
        query = query.filter(ExceptionRecord.status == status_filter)
    if severity:
        query = query.filter(ExceptionRecord.severity == severity)
    return query.order_by(ExceptionRecord.created_at.desc()).all()


@router.get("/{exception_id}", response_model=ExceptionOut, dependencies=[Depends(require_viewer)])
def get_exception(exception_id: str, db: Session = Depends(get_db)):
    exc = db.query(ExceptionRecord).filter(ExceptionRecord.exception_id == exception_id).first()
    if not exc:
        raise HTTPException(status_code=404, detail="Exception not found")
    return exc


@router.post("/{exception_id}/resolve", response_model=ExceptionOut)
def resolve_exception(
    exception_id: str,
    payload: ExceptionResolveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_procurement),
):
    exc = db.query(ExceptionRecord).filter(ExceptionRecord.exception_id == exception_id).first()
    if not exc:
        raise HTTPException(status_code=404, detail="Exception not found")

    if payload.action not in ("APPROVE", "REJECT"):
        raise HTTPException(status_code=400, detail="action must be APPROVE or REJECT")

    if payload.correct_po_id:
        po = db.query(POMaster).filter(POMaster.po_id == payload.correct_po_id).first()
        if not po:
            raise HTTPException(status_code=400, detail="correct_po_id does not reference an existing PO")
        db.add(AuditLog(
            entity_type="exceptions", entity_id=exc.exception_id, field="po_id",
            old_value=exc.po_id, new_value=payload.correct_po_id, action="UPDATE", user_id=user.user_id,
        ))
        exc.po_id = payload.correct_po_id

    if payload.field_corrections and exc.po_id:
        po = db.query(POMaster).filter(POMaster.po_id == exc.po_id).first()
        if po:
            for field, new_value in payload.field_corrections.items():
                if hasattr(po, field):
                    old_value = getattr(po, field)
                    db.add(AuditLog(
                        entity_type="po_master", entity_id=po.po_id, field=field,
                        old_value=str(old_value), new_value=str(new_value), action="UPDATE", user_id=user.user_id,
                    ))
                    setattr(po, field, new_value)
            metrics = compute_po_metrics(po)
            apply_metrics(po, metrics)

    exc.status = ExceptionStatus.APPROVED if payload.action == "APPROVE" else ExceptionStatus.REJECTED
    exc.resolution = payload.resolution
    exc.resolved_date = datetime.utcnow()

    db.add(AuditLog(
        entity_type="exceptions", entity_id=exc.exception_id, field="status",
        old_value=ExceptionStatus.OPEN.value, new_value=exc.status.value, action=payload.action, user_id=user.user_id,
    ))

    db.commit()
    db.refresh(exc)
    return exc
