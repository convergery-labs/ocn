"""AgentState TypedDict for the LangGraph graph."""
from typing import Optional, TypedDict


class AgentState(TypedDict):
    """State passed between nodes in the LangGraph graph."""

    prompt: str
    domain_slug: Optional[str]
    confidence: Optional[float]
    days_back: Optional[int]
    focus: Optional[str]
    run_id: Optional[str]
    articles: Optional[list[dict]]
    category_assignments: Optional[dict[str, str]]
    summaries: Optional[dict[str, str]]
    roll_up_summary: Optional[str]
    clarification_message: Optional[str]
