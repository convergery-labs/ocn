"""Single source of truth for per-article classification domains.

Scope: only domains classified one article at a time through
run_agent_pipeline's generic loop (news, geopolitical, and future domains of
the same shape, e.g. vc_commentary). sec_filing and taiwan_market_signal are
NOT here - they run through their own dedicated controllers
(controllers/filing_run.py, controllers/run.py's run_taiwan_signal_classification)
because their shape is genuinely different: filings need per-ticker XBRL/
exhibit fetching woven into classification, and Taiwan needs its whole batch
together for revenue ranking, not a per-article loop. Folding those in here
would hide real structural differences behind a false common interface.

Adding a new per-article domain (e.g. vc_commentary) means: write its prompt,
its classify_article-shaped function, its insert_*_classification function,
add one _build_*_config() function below, and add it to _BUILDERS - no
controllers/run.py edit required.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import config
from adapters.web_search import search_entity_context
from models.jobs import (
    get_recent_entity_classifications,
    insert_classification,
    insert_geopolitical_classification,
)
from pipeline.classifier import classify_article_two_stage, load_prompt
from pipeline.example_selector import ExampleSelector, parse_examples
from pipeline.geopolitical_classifier import classify_geopolitical_article, load_geopolitical_prompt

ClassifyOneFn = Callable[..., dict[str, Any]]
InsertFn = Callable[[int, dict[str, Any], dict[str, Any]], None]


@dataclass(frozen=True)
class DomainConfig:
    """Everything run_agent_pipeline needs to classify one domain's articles,
    one article at a time. classify_one is pre-bound to this domain's specific
    classify function, prompt(s), and any context-gathering it needs - callers
    pass only (article, batch_context) regardless of whether the underlying
    classifier is one-stage or two-stage, so run_agent_pipeline's loop stays
    domain-agnostic.
    """
    domain: str
    classify_one: ClassifyOneFn
    insert_fn: InsertFn


def _build_news_config() -> DomainConfig:
    system_prompt_v1 = load_prompt(config.DEFAULT_PROMPT)
    system_prompt_v2 = load_prompt(config.DEFAULT_PROMPT_V2)
    example_selector = ExampleSelector(parse_examples(system_prompt_v1))
    models = [config.OPENAI_MODEL]
    models_v2 = [config.OPENAI_MODEL_V2]

    def entity_history_fn(entity_names: list[str]) -> list[dict]:
        return get_recent_entity_classifications(entity_names)

    def web_search_fn(entity_names: list[str], signal_reason: str = "") -> list[dict]:
        results: list[dict] = []
        event_hint = signal_reason[:60].strip() if signal_reason else ""
        for i, name in enumerate(entity_names[:2]):
            query = f"{name} {event_hint}".strip() if event_hint else name
            results.extend(
                search_entity_context(
                    query,
                    provider=config.WEB_SEARCH_PROVIDER,
                    api_key=config.WEB_SEARCH_API_KEY,
                    # apply delay on 2nd+ query to avoid DuckDuckGo rate limiting
                    rate_delay=(i > 0 and config.WEB_SEARCH_PROVIDER == "duckduckgo"),
                )
            )
        return results

    def classify_one(article: dict[str, Any], *, batch_context: list[dict[str, Any]]) -> dict[str, Any]:
        return classify_article_two_stage(
            article,
            system_prompt_v1=system_prompt_v1,
            system_prompt_v2=system_prompt_v2,
            entity_history_fn=entity_history_fn,
            web_search_fn=web_search_fn,
            models=models,
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_BASE_URL,
            timeout=config.OPENAI_TIMEOUT,
            max_attempts=config.OPENAI_MAX_ATTEMPTS,
            batch_context=[b for b in batch_context if b["url"] != article.get("url")],
            example_selector=example_selector,
            models_v2=models_v2,
        )

    return DomainConfig(
        domain=config.NEWS_DOMAIN,
        classify_one=classify_one,
        insert_fn=insert_classification,
    )


def _build_geopolitical_config() -> DomainConfig:
    system_prompt = load_geopolitical_prompt()
    models = [config.OPENAI_MODEL]

    def classify_one(article: dict[str, Any], **_ignored: Any) -> dict[str, Any]:
        return classify_geopolitical_article(
            article,
            system_prompt=system_prompt,
            models=models,
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_BASE_URL,
            timeout=config.OPENAI_TIMEOUT,
            max_attempts=config.OPENAI_MAX_ATTEMPTS,
        )

    return DomainConfig(
        domain=config.GEOPOLITICAL_DOMAIN,
        classify_one=classify_one,
        insert_fn=insert_geopolitical_classification,
    )


_BUILDERS: dict[str, Callable[[], DomainConfig]] = {
    config.NEWS_DOMAIN: _build_news_config,
    config.GEOPOLITICAL_DOMAIN: _build_geopolitical_config,
}


def get_domain_config(domain: str) -> DomainConfig | None:
    """Return the DomainConfig for domain, or None if it isn't a registered
    per-article domain (e.g. sec_filing/taiwan_market_signal, which run
    through their own dedicated controllers, or an unrecognized domain).

    Built fresh on every call rather than cached - this runs once per
    background classification job (at most a few times a minute), not per
    article or per request, so re-reading prompt files and re-parsing the 75
    example blocks is negligible next to the LLM calls the job is about to
    make. Avoids a module-level mutable-state cache for a saving that
    wouldn't be measurable here.
    """
    builder = _BUILDERS.get(domain)
    return builder() if builder is not None else None


def known_domains() -> list[str]:
    return sorted(_BUILDERS)
