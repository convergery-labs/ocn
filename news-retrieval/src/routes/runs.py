"""Routes for /runs."""
import io
import os
import zipfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from models.reports import list_reports
from models.runs import get_run, list_runs

_REPORTS_DIR = os.environ.get("REPORTS_DIR", "/app/reports")

router = APIRouter()


@router.get("/runs")
def get_runs() -> list:
    """Return all pipeline runs, newest first."""
    return list_runs()


@router.get("/runs/{run_id}")
def get_run_by_id(run_id: int) -> dict:
    """Return a single pipeline run by id."""
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@router.get("/runs/{run_id}/reports")
def get_reports_for_run(run_id: int) -> list:
    """Return all report records for a run."""
    if get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return list_reports(run_id)


@router.get("/runs/{run_id}/reports/download")
def download_reports_for_run(run_id: int) -> Response:
    """Download all reports for a run as a ZIP archive."""
    if get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    reports = list_reports(run_id)
    if not reports:
        raise HTTPException(
            status_code=404, detail="No reports found for this run."
        )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for report in reports:
            filepath = os.path.join(_REPORTS_DIR, report["filename"])
            if os.path.isfile(filepath):
                zf.write(filepath, report["filename"])
    buf.seek(0)
    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="run_{run_id}_reports.zip"'
            )
        },
    )


