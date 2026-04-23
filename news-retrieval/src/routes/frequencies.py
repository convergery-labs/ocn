"""Routes for /frequencies."""
from fastapi import APIRouter, Depends, HTTPException

from typing import Any

from auth import require_admin
from db import DuplicateError
from models.frequencies import FrequencyIn, create_frequency, list_frequencies

router = APIRouter()


@router.get("/frequencies")
async def get_frequencies() -> list[dict]:
    """Return all polling frequencies."""
    return list_frequencies()


@router.post("/frequencies", status_code=201)
async def post_frequency(
    body: FrequencyIn,
    caller: dict[str, Any] = Depends(require_admin),
) -> dict:
    """Add a new polling frequency (admin only)."""
    try:
        return create_frequency(body)
    except DuplicateError:
        raise HTTPException(
            status_code=409,
            detail=f"Frequency '{body.name}' already exists.",
        )
