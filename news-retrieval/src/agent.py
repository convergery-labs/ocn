"""Core agent logic for the News Aggregator."""
import os
import time
import logging
import httpx
from typing import List

logger = logging.getLogger(__name__)
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from tools import make_fetch_news_tool, fetch_articles_content, make_save_report_tool


class _LLMTimingCallback(BaseCallbackHandler):
    """Log duration and token usage for every LLM call."""

    def __init__(self, agent_name: str):
        self._agent_name = agent_name
        self._call_start: float = 0.0
        self._call_index: int = 0

    def on_chat_model_start(self, serialized, messages, **kwargs):
        self._call_start = time.perf_counter()
        self._call_index += 1
        # Count tokens in the prompt as a rough size indicator
        total_chars = sum(
            len(m.content) if hasattr(m, "content") and isinstance(m.content, str) else 0
            for batch in messages
            for m in batch
        )
        logger.info(
            "[LLM] agent=%s call=%d started prompt_chars=%d",
            self._agent_name,
            self._call_index,
            total_chars,
        )

    def on_llm_end(self, response: LLMResult, **kwargs):
        elapsed = time.perf_counter() - self._call_start
        usage = {}
        if response.llm_output:
            usage = response.llm_output.get("token_usage", {})
        logger.info(
            "[LLM] agent=%s call=%d elapsed=%.2fs prompt_tokens=%s completion_tokens=%s",
            self._agent_name,
            self._call_index,
            elapsed,
            usage.get("prompt_tokens", "?"),
            usage.get("completion_tokens", "?"),
        )

_SYSTEM_PROMPT_TEMPLATE = """You are a {domain} news aggregator agent. When asked to gather
news, proceed immediately using the following defaults unless the request
explicitly overrides them:

  - days_back: 7
  - max_articles: 0 (no limit — fetch whatever the feeds provide)
  - summary_depth: detailed

Never ask for clarification. If a parameter is not specified, use its default.

General approach:
1. Call {fetch_tool_name} with the specified (or default) days_back and
max_articles values.
2. Call fetch_articles_content once, passing ALL article URLs as a list.
3. After receiving all article content, immediately begin calling
save_themed_report for each category — do NOT produce any intermediate text.
Assign each article to the single most relevant category from the taxonomy
below. Only produce a report for a category if at least 2 articles belong to
it. Call save_themed_report once per qualifying category, passing the full
markdown report content directly in the tool call.

Taxonomy — use these category names exactly, spelled and capitalised as shown:
{taxonomy}

Report format for each category:
- Top-level heading: category name and today's date.
- One section per relevant article:
    - Article title as a sub-heading.
    - Source URL on its own line.
    - A concise summary paragraph (length as specified; default: 2-4
      sentences).
- A final "Category Summary" section: a detailed, synthesised narrative
  covering the major trends, implications, and dynamics across all articles
  in this category. Write several paragraphs — go beyond listing.

CRITICAL: After fetching articles, your next action MUST be tool calls to
save_themed_report — never a text response. Do not summarise, explain, or
describe what you are about to do. Just call the tools. Category names in
every save_themed_report call must match the taxonomy exactly.
"""


def _build_instruction(
    days_back: int,
    max_articles: int,
    summary_depth: str,
    focus: str | None = None,
) -> str:
    """Build the per-run instruction message passed to the agent."""
    article_limit = str(max_articles) if max_articles else "all available"
    summary_spec = (
        "1-2 sentence summary per article"
        if summary_depth == "brief"
        else "2-4 sentence summary per article"
    )
    focus_line = f"- Focus: {focus}\n" if focus else ""
    return (
        f"Gather news with the following parameters:\n"
        f"- Time period: past {days_back} days\n"
        f"- Max articles to fetch: {article_limit}\n"
        f"- Per-article format: {summary_spec}\n"
        f"{focus_line}"
        f"\nAssign articles to categories from the taxonomy in the system "
        f"prompt (minimum 2 articles per category) and save a report for "
        f"every qualifying category before finishing."
    )


class NewsAgent:
    """
    A generalizable news agent.

    A configurable LangChain-based agent that fetches news from provided RSS
    feeds and writes per-category markdown reports using a given taxonomy.
    """

    def __init__(
        self,
        name: str,
        feeds: List[str],
        taxonomy: List[str],
        fetch_tool_name: str = "fetch_news",
    ):
        """
        Initialise the agent.

        Args:
            name: Human-readable domain name used in the system prompt
                  (e.g. "AI", "Smart Money").
            feeds: List of RSS feed URLs to poll.
            taxonomy: List of category names the agent must use verbatim.
            fetch_tool_name: Unique tool name for the fetch tool (must differ
                             between agents sharing the same process).
        """
        self.name = name
        self._report_collector: dict = {}
        self._article_registry: dict = {}  # url -> title; URLs removed as reports are saved
        self._total_fetched: int = 0

        fetch_news = make_fetch_news_tool(
            feeds,
            tool_name=fetch_tool_name,
            article_registry=self._article_registry,
            total_counter=self,
        )
        save_report = make_save_report_tool(
            self._report_collector, article_registry=self._article_registry
        )
        self.tools = [fetch_news, fetch_articles_content, save_report]

        taxonomy_str = "\n".join(f"  - {cat}" for cat in taxonomy)
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            domain=name,
            fetch_tool_name=fetch_tool_name,
            taxonomy=taxonomy_str,
        )

        # Callback must be created before the LLM so it can be passed directly.
        # Passing it only to AgentExecutor is not reliable — LangChain does not
        # always propagate executor-level callbacks down to the LLM layer.
        self._llm_callback = _LLMTimingCallback(name)
        self.llm = ChatOpenAI(
            # model="gpt-5.4",
            model="openai/gpt-5.4",
            # openai_api_key=os.environ.get("OPENAI_API_KEY"),
            openai_api_key=os.environ.get("OPENROUTER_API_KEY"),
            openai_api_base="https://openrouter.ai/api/v1",
            temperature=0,
            streaming=False,
            http_client=httpx.Client(http2=False),
            callbacks=[self._llm_callback],
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                ("user", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ]
        )

        agent = create_tool_calling_agent(self.llm, self.tools, prompt)
        self.agent_executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            verbose=False,
            max_iterations=150,
            handle_parsing_errors=True,
            stream_runnable=False,
        )

    def _collect_reports(self) -> dict:
        """Return collected reports and clear the collector for the next run."""
        reports = dict(self._report_collector)
        self._report_collector.clear()
        return reports

    def _log_coverage(self):
        uncategorized = dict(self._article_registry)
        if uncategorized:
            logger.info(
                "[COVERAGE] agent=%s uncategorized=%d/%d articles",
                self.name,
                len(uncategorized),
                self._total_fetched,
            )
            for url, title in uncategorized.items():
                logger.info("[COVERAGE] uncategorized: %s | %s", title, url)
        else:
            logger.info(
                "[COVERAGE] agent=%s all %d articles categorized",
                self.name,
                self._total_fetched,
            )

    def process_message(self, message_text: str) -> dict:
        """
        Process a free-form message from a parent agent or orchestrator.

        Returns:
            Dict with 'summary' (agent final output) and 'reports' (dict
            mapping category name → full markdown content).
        """
        self._report_collector.clear()
        self._article_registry.clear()
        result = self.agent_executor.invoke({"input": message_text})
        self._log_coverage()
        return {"summary": result["output"], "reports": self._collect_reports()}

    def run(
        self,
        days_back: int = 7,
        max_articles: int = 0,
        summary_depth: str = "detailed",
        focus: str | None = None,
    ) -> dict:
        """
        Run the agent with explicit parameters.

        Returns:
            Dict with 'summary' (agent final output) and 'reports' (dict
            mapping category name → full markdown content).
        """
        self._report_collector.clear()
        self._article_registry.clear()
        instruction = _build_instruction(
            days_back, max_articles, summary_depth, focus
        )
        t0 = time.perf_counter()
        result = self.agent_executor.invoke({"input": instruction})
        logger.info(
            "[TIMER] agent=%s run total elapsed=%.2fs reports=%d",
            self.name,
            time.perf_counter() - t0,
            len(self._report_collector),
        )
        self._log_coverage()
        return {"summary": result["output"], "reports": self._collect_reports()}
