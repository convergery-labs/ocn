"""Routes for /reports."""
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from models.reports import get_report

router = APIRouter()

_REPORTS_DIR = os.environ.get("REPORTS_DIR", "/app/reports")


@router.get("/reports/{report_id}")
def get_report_json(report_id: int) -> dict:
    """Return a report record with its markdown content."""
    report = get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    filepath = os.path.join(_REPORTS_DIR, report["filename"])
    try:
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail="Report file not found on disk."
        )
    return {**report, "content": content}


@router.get("/reports/{report_id}/download")
def download_report(report_id: int) -> FileResponse:
    """Serve a report as a downloadable markdown file."""
    report = get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    filepath = os.path.join(_REPORTS_DIR, report["filename"])
    if not os.path.isfile(filepath):
        raise HTTPException(
            status_code=404, detail="Report file not found on disk."
        )
    return FileResponse(
        path=filepath,
        filename=report["filename"],
        media_type="text/markdown",
    )
