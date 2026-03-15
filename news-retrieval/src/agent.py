"""Core agent logic for the News Aggregator."""
import os
import httpx
from typing import List
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents import AgentExecutor, create_tool_calling_agent

from tools import make_fetch_news_tool, fetch_articles_content, make_save_report_tool

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

        fetch_news = make_fetch_news_tool(feeds, tool_name=fetch_tool_name)
        save_report = make_save_report_tool(self._report_collector)
        self.tools = [fetch_news, fetch_articles_content, save_report]

        taxonomy_str = "\n".join(f"  - {cat}" for cat in taxonomy)
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            domain=name,
            fetch_tool_name=fetch_tool_name,
            taxonomy=taxonomy_str,
        )

        self.llm = ChatOpenAI(
            model="gpt-5.4",
            # model="openai/gpt-5.4",
            openai_api_key=os.environ.get("OPENAI_API_KEY"),
            # openai_api_key=os.environ.get("OPENROUTER_API_KEY"),
            # openai_api_base="https://openrouter.ai/api/v1",
            temperature=0,
            streaming=False,
            http_client=httpx.Client(http2=False),
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
            verbose=True,
            max_iterations=150,
            handle_parsing_errors=True,
            stream_runnable=False,
        )

    def _collect_reports(self) -> dict:
        """Return collected reports and clear the collector for the next run."""
        reports = dict(self._report_collector)
        self._report_collector.clear()
        return reports

    def process_message(self, message_text: str) -> dict:
        """
        Process a free-form message from a parent agent or orchestrator.

        Returns:
            Dict with 'summary' (agent final output) and 'reports' (dict
            mapping category name → full markdown content).
        """
        self._report_collector.clear()
        result = self.agent_executor.invoke({"input": message_text})
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
        instruction = _build_instruction(
            days_back, max_articles, summary_depth, focus
        )
        result = self.agent_executor.invoke({"input": instruction})
        return {"summary": result["output"], "reports": self._collect_reports()}
