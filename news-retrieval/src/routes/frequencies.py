"""Routes for /frequencies."""
from fastapi import APIRouter, HTTPException

from db import DuplicateError
from models.frequencies import FrequencyIn, create_frequency, list_frequencies

router = APIRouter()


@router.get("/frequencies")
async def get_frequencies() -> list[dict]:
    """Return all polling frequencies."""
    return list_frequencies()


@router.post("/frequencies", status_code=201)
async def post_frequency(body: FrequencyIn) -> dict:
    """Add a new polling frequency."""
    try:
        return create_frequency(body)
    except DuplicateError:
        raise HTTPException(
            status_code=409,
            detail=f"Frequency '{body.name}' already exists.",
        )
