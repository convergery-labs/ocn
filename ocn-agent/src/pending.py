"""Shared coordination state for async news-retrieval callbacks."""
import asyncio
from typing import Any

run_events: dict[str, asyncio.Event] = {}
run_results: dict[str, Any] = {}
