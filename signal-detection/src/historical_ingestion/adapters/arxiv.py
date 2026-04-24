"""arXiv Atom feed adapter for historical research paper ingestion."""
import logging
import time
from datetime import date

import feedparser
import requests

from historical_ingestion.adapters.base import AbstractHistoricalAdapter
from historical_ingestion.schema import HistoricalDocument

logger = logging.getLogger(__name__)

_ARXIV_API = "http://export.arxiv.org/api/query"
_PAGE_SIZE = 100
_RETRY_DELAY = 3.0  # arXiv asks for polite crawling


class ArXivAdapter(AbstractHistoricalAdapter):
    """Fetches research papers from the arXiv API.

    Paginates through all results matching the query and date range.
    Uses the paper abstract as the document body.
    """

    def fetch(
        self,
        query: str,
        date_from: date,
        date_to: date,
    ) -> list[HistoricalDocument]:
        """Return all arXiv papers matching *query* in the date range."""
        # arXiv date format for submittedDate: YYYYMMDDHHMMSS
        from_str = date_from.strftime("%Y%m%d") + "0000"
        to_str = date_to.strftime("%Y%m%d") + "2359"
        search_query = (
            f"all:{query}"
            f"+AND+submittedDate:[{from_str}+TO+{to_str}]"
        )

        docs: list[HistoricalDocument] = []
        start = 0

        while True:
            try:
                resp = requests.get(
                    _ARXIV_API,
                    params={
                        "search_query": search_query,
                        "start": start,
                        "max_results": _PAGE_SIZE,
                        "sortBy": "submittedDate",
                        "sortOrder": "descending",
                    },
                    timeout=30,
                )
                resp.raise_for_status()
            except Exception:
                logger.exception(
                    "arXiv API request failed at offset %d", start
                )
                break

            feed = feedparser.parse(resp.text)
            entries = feed.get("entries", [])
            if not entries:
                break

            for entry in entries:
                doc = _entry_to_document(entry)
                if doc is not None:
                    docs.append(doc)

            logger.info(
                "arXiv: fetched %d entries (offset %d)", len(entries), start
            )

            if len(entries) < _PAGE_SIZE:
                break

            start += _PAGE_SIZE
            time.sleep(_RETRY_DELAY)

        logger.info("arXiv: %d documents total", len(docs))
        return docs


def _entry_to_document(entry: dict) -> HistoricalDocument | None:
    """Convert a feedparser entry to a HistoricalDocument, or None."""
    url = entry.get("link", "").strip()
    title = entry.get("title", "").strip()
    summary = entry.get("summary", "").strip()

    if not url or not title or not summary:
        return None

    published = _parse_arxiv_date(entry.get("published", ""))
    if published is None:
        return None

    return HistoricalDocument(
        url=url,
        title=title,
        body=summary,
        source_type="research",
        published_date=published,
        source_adapter="arxiv",
        metadata={
            "arxiv_id": entry.get("id", ""),
            "authors": [
                a.get("name", "") for a in entry.get("authors", [])
            ],
        },
    )


def _parse_arxiv_date(published: str) -> date | None:
    """Parse arXiv published date (2017-06-12T...) into a date."""
    try:
        return date(
            int(published[:4]),
            int(published[5:7]),
            int(published[8:10]),
        )
    except Exception:
        return None
