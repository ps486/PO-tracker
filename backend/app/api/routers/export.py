from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ...db import get_db
from ...export.excel_export import export_po_tracker
from ...security import require_viewer

router = APIRouter(prefix="/api/export", tags=["export"], dependencies=[Depends(require_viewer)])


@router.get("/po-tracker.xlsx")
def export_po_tracker_xlsx(db: Session = Depends(get_db)):
    content = export_po_tracker(db)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=po_tracker.xlsx"},
    )
