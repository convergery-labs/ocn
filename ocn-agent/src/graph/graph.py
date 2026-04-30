"""LangGraph graph definition with node implementations."""
import asyncio
import logging
import os
import uuid
from typing import Optional

import httpx
from langchain_anthropic import ChatAnthropic
from langgraph.graph import END, StateGraph
from pydantic import BaseModel

import pending
from clients.news_retrieval import NewsRetrievalClient
from config import DOMAINS
from state import AgentState

logger = logging.getLogger(__name__)

_CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.7"))
_MAX_DAYS_BACK = 7

_DOMAIN_LIST = "\n".join(
    f"- {slug}: {cfg['description']}"
    for slug, cfg in DOMAINS.items()
)

_RESOLVE_SYSTEM_PROMPT = f"""You resolve a natural-language news query to one of
the available domains and extract query parameters.

Available domains:
{_DOMAIN_LIST}

Return JSON with these fields:
- domain_slug: one of the domain slugs above, or null if ambiguous
- confidence: float 0-1 indicating how confident you are in the mapping
- days_back: integer days to look back (inferred from temporal cues, max 7)
- focus: a concise directive rephrased from the query, or null if none
- clarification_message: if domain_slug is null or confidence is low, a
  plain-text question to ask the user; otherwise null
"""


class _DomainResolution(BaseModel):
    """Structured output schema for domain resolution."""

    domain_slug: Optional[str]
    confidence: float
    days_back: int
    focus: Optional[str]
    clarification_message: Optional[str]


def _build_llm() -> ChatAnthropic:
    """Build a ChatAnthropic instance from env vars."""
    return ChatAnthropic(
        model=os.environ["AGENT_LLM_MODEL"],
        api_key=os.environ["ANTHROPIC_API_KEY"],
    )


async def _fire_callback(url: str, payload: dict) -> None:
    """POST payload to url; best-effort, 10-second timeout."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json=payload)
    except Exception as exc:
        logger.warning("Callback delivery failed to %s: %s", url, exc)


def parse_prompt(state: AgentState) -> AgentState:
    """Parse and normalise the incoming prompt."""
    return state


async def resolve_domain_and_params(state: AgentState) -> AgentState:
    """Resolve domain slug and query parameters from the prompt via LLM."""
    llm = _build_llm()
    structured = llm.with_structured_output(_DomainResolution)
    result: _DomainResolution = await structured.ainvoke(
        [
            {"role": "system", "content": _RESOLVE_SYSTEM_PROMPT},
            {"role": "user", "content": state["prompt"]},
        ]
    )

    days_back = min(result.days_back, _MAX_DAYS_BACK)
    confidence = result.confidence

    if confidence < _CONFIDENCE_THRESHOLD or not result.domain_slug:
        clarification = (
            result.clarification_message
            or "Could you clarify which domain you're interested in?"
        )
        return {**state, "clarification_message": clarification}

    return {
        **state,
        "domain_slug": result.domain_slug,
        "confidence": confidence,
        "days_back": days_back,
        "focus": result.focus,
        "clarification_message": None,
    }


def _route_after_resolve(state: AgentState) -> str:
    """Route to clarification or main pipeline based on confidence."""
    if state.get("clarification_message"):
        return "return_clarification"
    return "call_news_retrieval"


async def call_news_retrieval(state: AgentState) -> AgentState:
    """Fetch articles from the news-retrieval service."""
    correlation_id = str(uuid.uuid4())
    agent_base_url = os.environ["AGENT_BASE_URL"]
    nr_callback_url = (
        f"{agent_base_url}/agent/news-retrieval-callback/{correlation_id}"
    )

    event = asyncio.Event()
    pending.run_events[correlation_id] = event

    client = NewsRetrievalClient()
    try:
        response = await client.create_run(
            domain_slug=state["domain_slug"],
            days_back=state["days_back"],
            focus=state.get("focus"),
            callback_url=nr_callback_url,
        )
    except Exception:
        pending.run_events.pop(correlation_id, None)
        await client.aclose()
        raise

    status_code = response["status_code"]
    body = response["body"]

    if status_code == 200:
        # Cache hit — run already complete, no callback will arrive
        run_id = body["id"]
        pending.run_events.pop(correlation_id, None)
    else:
        # New run — wait for news-retrieval to call back
        try:
            await asyncio.wait_for(event.wait(), timeout=300.0)
        except asyncio.TimeoutError:
            pending.run_events.pop(correlation_id, None)
            pending.run_results.pop(correlation_id, None)
            await client.aclose()
            raise RuntimeError("news-retrieval callback timed out")

        callback_payload = pending.run_results.pop(correlation_id, {})
        pending.run_events.pop(correlation_id, None)
        run_id = callback_payload.get("run_id")

    articles = await client.get_articles(run_id)
    await client.aclose()

    return {**state, "run_id": run_id, "articles": articles}


def categorise(state: AgentState) -> AgentState:
    """Assign vertical categories to each article."""
    return state


def summarise(state: AgentState) -> AgentState:
    """Summarise articles per category and produce a roll-up summary."""
    return state


async def return_result(state: AgentState) -> AgentState:
    """Deliver the completed-run payload to the caller's callback URL."""
    callback_url = state.get("callback_url")
    if callback_url:
        await _fire_callback(
            callback_url,
            {
                "status": "completed",
                "domain_slug": state.get("domain_slug"),
                "days_back": state.get("days_back"),
                "focus": state.get("focus"),
                "run_id": state.get("run_id"),
            },
        )
    return state


async def return_clarification(state: AgentState) -> AgentState:
    """Deliver a clarification request to the caller's callback URL."""
    callback_url = state.get("callback_url")
    if callback_url:
        await _fire_callback(
            callback_url,
            {
                "status": "needs_clarification",
                "message": state.get("clarification_message"),
            },
        )
    return state


builder: StateGraph = StateGraph(AgentState)

builder.add_node("parse_prompt", parse_prompt)
builder.add_node("resolve_domain_and_params", resolve_domain_and_params)
builder.add_node("call_news_retrieval", call_news_retrieval)
builder.add_node("categorise", categorise)
builder.add_node("summarise", summarise)
builder.add_node("return_result", return_result)
builder.add_node("return_clarification", return_clarification)

builder.set_entry_point("parse_prompt")
builder.add_edge("parse_prompt", "resolve_domain_and_params")
builder.add_conditional_edges(
    "resolve_domain_and_params",
    _route_after_resolve,
    {
        "call_news_retrieval": "call_news_retrieval",
        "return_clarification": "return_clarification",
    },
)
builder.add_edge("call_news_retrieval", "categorise")
builder.add_edge("categorise", "summarise")
builder.add_edge("summarise", "return_result")
builder.add_edge("return_result", END)
builder.add_edge("return_clarification", END)

graph = builder.compile()
