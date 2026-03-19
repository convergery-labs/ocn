"""FastAPI server for the News Aggregator agents."""
import logging
import os
import uuid
import click
import uvicorn
from datetime import datetime
from typing import Literal, Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agent import NewsAgent
from feeds import AI_NEWS_FEEDS, SMART_MONEY_FEEDS
from models import (
    JsonRpcRequest, JsonRpcResponse, Task, TaskStatus, Artifact, ArtifactPart
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("news-aggregator")

app = FastAPI(title="News Aggregator")

# ---------------------------------------------------------------------------
# Agent instances
# ---------------------------------------------------------------------------

AI_TAXONOMY = [
    "AI Agents & Automation",
    "AI Models & Research",
    "AI Hardware & Semiconductors",
    "Data Center Infrastructure",
    "Energy & Sustainability",
    "Robotics & Physical AI",
    "Edge & Local AI",
    "Enterprise AI & Productivity",
    "AI Security & Privacy",
    "AI Policy & Governance",
    "AI Funding & Startups",
    "AI in Science & Society",
]

SMART_MONEY_TAXONOMY = [
    "Agentic Payments & AI Wallets",
    "Machine Economy & AI-to-AI Transactions",
    "Stablecoins & On-Chain Settlement",
    "Cross-Border Payments & Real-Time Settlement",
    "Embedded Finance & API Banking",
    "AI Fraud Detection & Compliance",
    "Treasury Automation & Enterprise Finance",
]

ai_agent = NewsAgent(
    name="AI",
    feeds=AI_NEWS_FEEDS,
    taxonomy=AI_TAXONOMY,
    fetch_tool_name="fetch_ai_news",
)

smart_money_agent = NewsAgent(
    name="Smart Money",
    feeds=SMART_MONEY_FEEDS,
    taxonomy=SMART_MONEY_TAXONOMY,
    fetch_tool_name="fetch_smart_money_news",
)

# ---------------------------------------------------------------------------
# Usage docs
# ---------------------------------------------------------------------------

_USAGE = {
    "description": (
        "News Aggregator — fetches recent news from curated RSS feeds, "
        "extracts article content, and saves per-category markdown reports."
    ),
    "endpoints": {
        "POST /": (
            "A2A JSON-RPC 2.0 endpoint for agent-to-agent calls. Send a "
            "natural language message describing what you want. Include 'AI news' "
            "or 'smart money' in the message to route to the correct agent."
        ),
        "POST /ai-news-summary": (
            "REST endpoint for AI news aggregation. Accepts explicit "
            "parameters as a JSON body."
        ),
        "POST /smart-money-summary": (
            "REST endpoint for Smart Money news aggregation. Accepts explicit "
            "parameters as a JSON body."
        ),
    },
    "rest_parameters": {
        "days_back": {
            "type": "integer",
            "default": 7,
            "description": "How many days back to retrieve articles (min 1).",
        },
        "max_articles": {
            "type": "integer | null",
            "default": None,
            "description": (
                "Maximum number of articles to fetch across all feeds. "
                "Defaults to null (no limit — feeds self-limit naturally)."
            ),
        },
        "summary_depth": {
            "type": "string",
            "default": "detailed",
            "allowed": ["brief", "detailed"],
            "description": (
                "'brief' writes 1-2 sentence summaries per article. "
                "'detailed' writes 2-4 sentence summaries per article."
            ),
        },
        "focus": {
            "type": "string | null",
            "default": None,
            "description": (
                "Optional instruction to narrow the categories or topics "
                "covered, e.g. 'focus on GPU hardware and energy only'."
            ),
        },
    },
}


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class NewsRequest(BaseModel):
    """Parameters for a news aggregation run."""

    days_back: int = Field(default=7, ge=1, description="Days back to fetch articles.")
    max_articles: Optional[int] = Field(
        default=None, ge=1, description="Cap on total articles fetched; null for no limit."
    )
    summary_depth: Literal["brief", "detailed"] = Field(
        default="detailed", description="Depth of per-article summaries."
    )
    focus: Optional[str] = Field(
        default=None, description="Optional instruction to narrow topics covered."
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def usage():
    """Return usage instructions for the News Aggregator."""
    return _USAGE


@app.get("/health")
async def health():
    """Return the health status of the server and its dependencies."""
    checks = {}

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    # api_key = os.environ.get("OPENAI_API_KEY", "")
    checks["api_key_configured"] = bool(api_key)

    reports_dir = os.environ.get("REPORTS_DIR", "/app/reports")
    try:
        os.makedirs(reports_dir, exist_ok=True)
        test_path = os.path.join(reports_dir, ".healthcheck")
        with open(test_path, "w") as f:
            f.write("")
        os.remove(test_path)
        checks["reports_dir_writable"] = True
    except OSError:
        checks["reports_dir_writable"] = False

    healthy = all(checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "checks": checks},
    )


@app.post("/")
async def handle_rpc(request: JsonRpcRequest):
    """Handle A2A JSON-RPC 2.0 requests from parent agents."""
    if request.method != "message/send":
        return JsonRpcResponse(
            id=request.id,
            result=Task(
                id=request.id,
                status=TaskStatus(state="failed", timestamp=datetime.now().isoformat()),
            ),
        )

    input_text = "".join(
        part.text for part in request.params.message.parts
        if part.kind == "text" and part.text
    )
    session_id = request.params.session_id
    logger.info(f"A2A message received: {input_text[:80]}... (session={session_id})")

    text_lower = input_text.lower()
    if "smart money" in text_lower or "fintech" in text_lower or "payments" in text_lower:
        selected_agent = smart_money_agent
        logger.info("Routing to Smart Money agent")
    else:
        selected_agent = ai_agent
        logger.info("Routing to AI News agent")

    agent_result = selected_agent.process_message(input_text)

    response_parts = [agent_result["summary"]] if agent_result["summary"] else []
    for category, content in agent_result["reports"].items():
        response_parts.append(f"\n---\n## {category}\n\n{content}")
    response_text = "\n".join(response_parts)

    context_id = session_id or str(uuid.uuid4())
    return JsonRpcResponse(
        id=request.id,
        result=Task(
            id=str(uuid.uuid4()),
            status=TaskStatus(state="completed", timestamp=datetime.now().isoformat()),
            artifacts=[Artifact(parts=[ArtifactPart(text=response_text)])],
            contextId=context_id,
        ),
    )


@app.post("/ai-news-summary")
async def ai_news_summary(request: NewsRequest):
    """Run the AI news aggregation agent and return the full result."""
    max_articles = request.max_articles if request.max_articles is not None else 0
    logger.info(
        f"AI news run: days_back={request.days_back}, "
        f"max_articles={max_articles or 'unlimited'}, "
        f"summary_depth={request.summary_depth}"
    )
    result = ai_agent.run(
        days_back=request.days_back,
        max_articles=max_articles,
        summary_depth=request.summary_depth,
        focus=request.focus,
    )
    return {
        "status": "completed",
        "summary": result["summary"],
        "reports": result["reports"],
        "parameters_used": {
            "days_back": request.days_back,
            "max_articles": max_articles or "unlimited",
            "summary_depth": request.summary_depth,
        },
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/smart-money-summary")
async def smart_money_summary(request: NewsRequest):
    """Run the Smart Money aggregation agent and return the full result."""
    max_articles = request.max_articles if request.max_articles is not None else 0
    logger.info(
        f"Smart Money run: days_back={request.days_back}, "
        f"max_articles={max_articles or 'unlimited'}, "
        f"summary_depth={request.summary_depth}"
    )
    result = smart_money_agent.run(
        days_back=request.days_back,
        max_articles=max_articles,
        summary_depth=request.summary_depth,
        focus=request.focus,
    )
    return {
        "status": "completed",
        "summary": result["summary"],
        "reports": result["reports"],
        "parameters_used": {
            "days_back": request.days_back,
            "max_articles": max_articles or "unlimited",
            "summary_depth": request.summary_depth,
        },
        "timestamp": datetime.now().isoformat(),
    }


if __name__ == "__main__":
    @click.command()
    @click.option('--host', default='0.0.0.0')
    @click.option('--port', default=8000)
    def main(host: str, port: int):
        uvicorn.run(app, host=host, port=port)

    main()
