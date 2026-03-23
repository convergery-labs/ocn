"""Core agent logic for the News Aggregator."""
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait as futures_wait
from datetime import datetime
from typing import List

import httpx
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from tools import make_fetch_news_tool, make_save_report_tool

logger = logging.getLogger(__name__)


class _LLMTimingCallback(BaseCallbackHandler):
    """Log duration and token usage for every LLM call."""

    def __init__(self, agent_name: str):
        """Args: agent_name: label used in log output."""
        self._agent_name = agent_name
        self._call_start: float = 0.0
        self._call_index: int = 0
        self._lock = threading.Lock()

    def on_chat_model_start(self, serialized, messages, **kwargs):
        """Record start time and log prompt size."""
        with self._lock:
            self._call_index += 1
            call_index = self._call_index
        self._call_start = time.perf_counter()
        total_chars = sum(
            len(m.content)
            if hasattr(m, "content") and isinstance(m.content, str)
            else 0
            for batch in messages
            for m in batch
        )
        logger.info(
            "[LLM] agent=%s call=%d started prompt_chars=%d",
            self._agent_name,
            call_index,
            total_chars,
        )

    def on_llm_end(self, response: LLMResult, **kwargs):
        """Log elapsed time and token usage for the completed LLM call."""
        elapsed = time.perf_counter() - self._call_start
        usage = {}
        if response.llm_output:
            usage = response.llm_output.get("token_usage", {})
        logger.info(
            "[LLM] agent=%s elapsed=%.2fs"
            " prompt_tokens=%s completion_tokens=%s",
            self._agent_name,
            elapsed,
            usage.get("prompt_tokens", "?"),
            usage.get("completion_tokens", "?"),
        )


class _RateLimiter:
    """Token bucket rate limiter for concurrent threads."""

    def __init__(self, rate: float):
        """Args: rate: max calls per second (also the burst cap)."""
        self._rate = rate
        self._tokens = float(rate)
        self._last_refill = time.perf_counter()
        self._lock = threading.Lock()

    def acquire(self):
        """Block until a token is available."""
        while True:
            with self._lock:
                now = time.perf_counter()
                self._tokens = min(
                    self._rate,
                    self._tokens + (now - self._last_refill) * self._rate,
                )
                self._last_refill = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
            time.sleep(0.05)


_PASS1_BATCH_SIZE = 5


class _ArticleAssignment(BaseModel):
    url: str
    category: str  # exact taxonomy name, or "none"


class _BatchCategories(BaseModel):
    assignments: list[_ArticleAssignment]


class _RunParams(BaseModel):
    days_back: int = 7
    summary_depth: str = "detailed"  # "brief" or "detailed"
    focus: str | None = None


class NewsAgent:
    """A generalizable news agent.

    Uses a two-pass parallel pipeline:
    - Pass 1: Categorize each article in parallel using RSS summaries
    - Pass 2: Write one report per qualifying category in parallel
    """

    def __init__(
        self,
        name: str,
        feeds: List[str],
        taxonomy: List[str],
        fetch_tool_name: str = "fetch_news",
        weekly_feeds: List[str] | None = None,
    ):
        """Initialise the agent.

        Args:
            name: Human-readable domain name used in the system prompt
                  (e.g. "AI", "Smart Money").
            feeds: List of RSS feed URLs to poll.
            taxonomy: List of category names the agent must use verbatim.
            fetch_tool_name: Unique tool name for the fetch tool (must differ
                             between agents sharing the same process).
            weekly_feeds: Optional feeds polled only when days_back >= 7.
        """
        self.name = name
        self._taxonomy = taxonomy
        self._taxonomy_set = set(taxonomy)
        self._report_collector: dict = {}
        # url -> title; URLs removed from registry as reports are saved
        self._article_registry: dict = {}
        self._total_fetched: int = 0

        self._fetch_news = make_fetch_news_tool(
            feeds,
            tool_name=fetch_tool_name,
            article_registry=self._article_registry,
            total_counter=self,
            weekly_feeds=weekly_feeds,
        )
        self._save_report = make_save_report_tool(
            self._report_collector, article_registry=self._article_registry
        )

        self._rate_limiter = _RateLimiter(rate=15.0)
        self._llm_callback = _LLMTimingCallback(name)
        _llm_common = dict(
            openai_api_key=os.environ.get("OPENROUTER_API_KEY"),
            openai_api_base="https://openrouter.ai/api/v1",
            temperature=0,
            streaming=False,
            max_retries=0,
            http_client=httpx.Client(http2=False, timeout=60.0),
            callbacks=[self._llm_callback],
        )
        # Pass 1: structured output — fast and reliable for categorization
        self._llm_pass1 = ChatOpenAI(model="openai/gpt-4o-mini", **_llm_common)
        # Pass 2: higher output token throughput for report generation
        self.llm = ChatOpenAI(
            model="anthropic/claude-haiku-4-5", **_llm_common
        )

    def _collect_reports(self) -> dict:
        """Return collected reports and clear the collector for the next run."""
        reports = dict(self._report_collector)
        self._report_collector.clear()
        return reports

    def _log_coverage(self):
        """Log how many fetched articles were left uncategorized."""
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

    def _pass1_categorize(self, articles, focus=None):
        """Categorize articles in parallel batches.

        Returns:
            dict mapping category name to list of article URLs.
        """
        taxonomy_str = "\n".join(f"  - {cat}" for cat in self._taxonomy)
        focus_line = f"\nAdditional focus: {focus}" if focus else ""
        system_msg = (
            f"You are a {self.name} news categorization assistant.\n"
            "Assign each article to the single most relevant category"
            " from the taxonomy below.\n"
            "Use the category name exactly as given."
            " If no category fits, use \"none\".\n"
            "Return one assignment per article"
            " using the article's exact URL.\n\n"
            "IMPORTANT: Only assign a category if the article is"
            f" directly and primarily about {self.name}-related topics."
            " Articles that are only tangentially related, or primarily"
            " about a different field, must return \"none\".\n\n"
            f"Taxonomy:\n{taxonomy_str}{focus_line}"
        )
        structured_llm = self._llm_pass1.with_structured_output(
            _BatchCategories
        )

        def _categorize_batch(batch):
            self._rate_limiter.acquire()
            articles_text = "\n\n".join(
                f"Article {i + 1}:\nURL: {a['url']}\nTitle: \"{a['title']}\"\n"
                f"Source: {a['source']}\nSummary: {a.get('summary', '')}"
                for i, a in enumerate(batch)
            )
            result = structured_llm.invoke([
                {"role": "system", "content": system_msg},
                {"role": "user", "content": articles_text},
            ])
            return [
                (assignment.url, assignment.category)
                for assignment in result.assignments
            ]

        batches = [
            articles[i:i + _PASS1_BATCH_SIZE]
            for i in range(0, len(articles), _PASS1_BATCH_SIZE)
        ]
        category_map: dict[str, list[str]] = {}
        t0 = time.perf_counter()
        executor = ThreadPoolExecutor(max_workers=15)
        try:
            futures = {
                executor.submit(_categorize_batch, b): b for b in batches
            }
            done, not_done = futures_wait(futures, timeout=90)
            if not_done:
                logger.warning(
                    "[PASS1] agent=%s %d batches timed out",
                    self.name,
                    len(not_done),
                )
            for future in done:
                try:
                    for url, category in future.result():
                        if category != "none" and category in self._taxonomy_set:
                            category_map.setdefault(category, []).append(url)
                except Exception as e:
                    logger.warning(
                        "[PASS1] agent=%s batch failed err=%s", self.name, e
                    )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        qualifying = {
            cat: urls for cat, urls in category_map.items() if len(urls) >= 2
        }
        logger.info(
            "[PASS1] agent=%s articles=%d batches=%d"
            " qualifying_categories=%d elapsed=%.2fs",
            self.name,
            len(articles),
            len(batches),
            len(qualifying),
            time.perf_counter() - t0,
        )
        return qualifying

    def _pass2_write_reports(self, qualifying, article_meta, summary_depth):
        """Write one report per qualifying category in parallel.

        Returns:
            dict mapping category name to markdown content.
        """
        today = datetime.now().strftime("%Y-%m-%d")

        def _write_one(category, urls):
            self._rate_limiter.acquire()
            articles = [
                article_meta[url] for url in urls if url in article_meta
            ]
            articles_text = "\n---\n".join(
                f"Title: {a['title']}\nURL: {a['url']}\n"
                f"Summary: {a.get('summary', '')}"
                for a in articles
            )
            system_msg = (
                f"You are a {self.name} news analyst."
                " Write a complete markdown report for the"
                f" category \"{category}\""
                " using the article summaries provided.\n\n"
                "Report format:\n"
                f"# {category} — {today}\n\n"
                "## {Article Title}\n"
                "{url}\n"
                "{summary paragraph}\n\n"
                "[one section per article]\n\n"
                "## Category Summary\n"
                "[Several paragraphs synthesizing major trends,"
                " implications, and dynamics. "
                "Go beyond listing — provide insight and analysis."
                " Assess the magnitude of each development against the"
                " baseline of prior years; reserve 'inflection point'"
                " language only where the evidence shows a change in kind"
                " rather than degree, and flag when a trend is a"
                " continuation.]\n\n"
                "Use article titles and URLs exactly as given."
            )
            user_msg = f"Category: {category}\n\nArticles:\n{articles_text}"
            result = self.llm.invoke([
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ])
            return category, result.content

        reports = {}
        t0 = time.perf_counter()
        executor = ThreadPoolExecutor(max_workers=15)
        try:
            futures = {
                executor.submit(_write_one, cat, urls): cat
                for cat, urls in qualifying.items()
            }
            done, not_done = futures_wait(futures, timeout=120)
            if not_done:
                logger.warning(
                    "[PASS2] agent=%s %d reports timed out",
                    self.name,
                    len(not_done),
                )
            for future in done:
                try:
                    category, markdown = future.result()
                    reports[category] = markdown
                except Exception as e:
                    logger.warning(
                        "[PASS2] agent=%s report failed err=%s", self.name, e
                    )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        logger.info(
            "[PASS2] agent=%s categories=%d reports=%d elapsed=%.2fs",
            self.name,
            len(qualifying),
            len(reports),
            time.perf_counter() - t0,
        )
        return reports

    def run(
        self,
        days_back: int = 7,
        max_articles: int = 0,
        summary_depth: str = "detailed",
        focus: str | None = None,
    ) -> dict:
        """Run the two-pass pipeline.

        Returns:
            Dict with 'summary' and 'reports' (category → markdown).
        """
        self._report_collector.clear()
        self._article_registry.clear()
        t0 = time.perf_counter()

        raw_json = self._fetch_news.invoke(
            {"days_back": days_back, "max_articles": max_articles}
        )
        articles = json.loads(raw_json)
        if not articles:
            return {"summary": "No articles found.", "reports": {}}

        article_meta = {a["url"]: a for a in articles}

        qualifying = self._pass1_categorize(articles, focus=focus)
        if not qualifying:
            return {"summary": "No qualifying categories.", "reports": {}}

        reports = self._pass2_write_reports(
            qualifying, article_meta, summary_depth
        )

        for category, report_md in reports.items():
            self._save_report.invoke({"theme": category, "content": report_md})

        logger.info(
            "[TIMER] agent=%s run total elapsed=%.2fs reports=%d",
            self.name,
            time.perf_counter() - t0,
            len(self._report_collector),
        )
        self._log_coverage()
        return {
            "summary": (
                f"Completed {self.name} digest:"
                f" {len(qualifying)} categories."
            ),
            "reports": self._collect_reports(),
        }

    def process_message(self, message_text: str) -> dict:
        """Process a free-form message from a parent agent or orchestrator.

        Returns:
            Dict with 'summary' and 'reports' (category → markdown).
        """
        params_llm = self._llm_pass1.with_structured_output(_RunParams)
        params = params_llm.invoke([
            {"role": "system", "content": (
                "Extract run parameters from the user's news request.\n"
                "- days_back: number of days back to fetch (default 7; "
                "'today', 'last day', 'past day' = 1)\n"
                "- summary_depth: 'brief' if they want short summaries,"
                " else 'detailed'\n"
                "- focus: any specific topic focus mentioned, or null"
            )},
            {"role": "user", "content": message_text},
        ])
        logger.info(
            "[PARAMS] agent=%s days_back=%d summary_depth=%s focus=%s",
            self.name,
            params.days_back,
            params.summary_depth,
            params.focus,
        )
        return self.run(
            days_back=params.days_back,
            summary_depth=params.summary_depth,
            focus=params.focus,
        )
