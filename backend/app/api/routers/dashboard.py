from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import ExceptionRecord, ExceptionStatus, POMaster
from ...schemas import DashboardKPIs
from ...security import require_viewer
from ...status.po_status import compute_po_metrics

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(require_viewer)])


@router.get("/kpis", response_model=DashboardKPIs)
def kpis(db: Session = Depends(get_db)):
    pos = db.query(POMaster).all()
    metrics_by_po = {po.po_id: compute_po_metrics(po) for po in pos}

    total_pos = len(pos)
    total_po_value = sum((po.total_po_value or Decimal(0) for po in pos), Decimal(0))
    closed = sum(1 for m in metrics_by_po.values() if m.computed_status.value in ("CLOSED",))
    overdue = sum(1 for m in metrics_by_po.values() if m.computed_status.value == "OVERDUE")
    duplicate = sum(1 for po in pos if po.status.value == "DUPLICATE")
    open_pos = total_pos - closed - duplicate

    pending_delivery_value = sum((m.balance_value for m in metrics_by_po.values()), Decimal(0))
    received_value = sum((m.received_value for m in metrics_by_po.values()), Decimal(0))
    pending_invoice_value = sum(
        (max((po.total_po_value or Decimal(0)) - m.invoice_value, Decimal(0)) for po, m in zip(pos, metrics_by_po.values())),
        Decimal(0),
    )
    open_exceptions = db.query(ExceptionRecord).filter(ExceptionRecord.status == ExceptionStatus.OPEN).count()

    return DashboardKPIs(
        total_pos=total_pos,
        total_po_value=total_po_value,
        open_pos=open_pos,
        closed_pos=closed,
        overdue_pos=overdue,
        pending_delivery_value=pending_delivery_value,
        received_value=received_value,
        pending_invoice_value=pending_invoice_value,
        exceptions=open_exceptions,
        duplicate_pos=duplicate,
    )


@router.get("/vendor-analysis")
def vendor_analysis(db: Session = Depends(get_db)):
    pos = db.query(POMaster).all()
    by_vendor: dict[str, dict] = defaultdict(lambda: {
        "po_count": 0, "po_value": Decimal(0), "received_value": Decimal(0),
        "pending_value": Decimal(0), "overdue_count": 0, "overdue_days": [],
    })
    for po in pos:
        vendor = po.vendor_name or "Unknown"
        metrics = compute_po_metrics(po)
        row = by_vendor[vendor]
        row["po_count"] += 1
        row["po_value"] += po.total_po_value or Decimal(0)
        row["received_value"] += metrics.received_value
        row["pending_value"] += metrics.balance_value
        if metrics.is_overdue:
            row["overdue_count"] += 1
            if metrics.days_overdue:
                row["overdue_days"].append(metrics.days_overdue)

    result = []
    for vendor, row in by_vendor.items():
        avg_overdue = sum(row["overdue_days"]) / len(row["overdue_days"]) if row["overdue_days"] else 0
        result.append({
            "vendor": vendor,
            "po_count": row["po_count"],
            "po_value": row["po_value"],
            "received": row["received_value"],
            "pending": row["pending_value"],
            "overdue": row["overdue_count"],
            "avg_overdue_days": round(avg_overdue, 1),
        })
    return sorted(result, key=lambda r: r["po_value"], reverse=True)


@router.get("/ageing")
def ageing(db: Session = Depends(get_db)):
    today = datetime.utcnow().date()
    buckets = {"0-7": 0, "8-15": 0, "16-30": 0, "31-60": 0, ">60": 0}
    pos = db.query(POMaster).all()
    for po in pos:
        metrics = compute_po_metrics(po)
        if metrics.computed_status.value in ("CLOSED", "CANCELLED"):
            continue
        if not po.po_date:
            continue
        age = (today - po.po_date).days
        if age <= 7:
            buckets["0-7"] += 1
        elif age <= 15:
            buckets["8-15"] += 1
        elif age <= 30:
            buckets["16-30"] += 1
        elif age <= 60:
            buckets["31-60"] += 1
        else:
            buckets[">60"] += 1
    return buckets


@router.get("/daily-summary")
def daily_summary(db: Session = Depends(get_db)):
    today = datetime.utcnow().date()
    start = datetime.combine(today, datetime.min.time())
    end = start + timedelta(days=1)

    new_pos = db.query(POMaster).filter(POMaster.created_at >= start, POMaster.created_at < end).all()
    new_po_value = sum((po.total_po_value or Decimal(0) for po in new_pos), Decimal(0))
    new_exceptions = db.query(ExceptionRecord).filter(
        ExceptionRecord.created_at >= start, ExceptionRecord.created_at < end
    ).count()
    overdue_pos = sum(
        1 for po in db.query(POMaster).all() if compute_po_metrics(po).computed_status.value == "OVERDUE"
    )

    return {
        "date": today.isoformat(),
        "new_pos": len(new_pos),
        "new_po_value": new_po_value,
        "new_exceptions": new_exceptions,
        "overdue_pos": overdue_pos,
    }
