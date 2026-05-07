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
_MAX_RESULTS = 1000   # hard cap across all pages
_RETRY_DELAY = 15.0   # arXiv rate-limits aggressive pagination; 15s avoids 429s
_MAX_RETRIES = 5
_BACKOFF_BASE = 60.0  # seconds; doubles each retry


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
        """Return arXiv papers matching *query* in the date range.

        Paginates until exhausted or _MAX_RESULTS is reached.
        """
        # For Lucene expressions (contain ":"), omit the server-side date filter
        # so arXiv can serve the query from cache. Date filtering is applied
        # client-side: entries outside [date_from, date_to] are dropped, and
        # pagination stops as soon as a page contains entries older than
        # date_from (results are sorted descending by submittedDate).
        #
        # For plain keyword queries, keep the server-side date filter — the
        # query is simple enough that arXiv handles it efficiently.
        if ":" in query:
            search_query = f"({query})"
            client_side_filter = True
        else:
            from_str = date_from.strftime("%Y%m%d")
            to_str = date_to.strftime("%Y%m%d")
            quoted = f'"{query}"' if " " in query else query
            search_query = (
                f"all:{quoted} AND submittedDate:[{from_str} TO {to_str}]"
            )
            client_side_filter = False

        docs: list[HistoricalDocument] = []
        start = 0

        while len(docs) < _MAX_RESULTS:
            resp = _fetch_page_with_retry(search_query, start)
            if resp is None:
                break

            feed = feedparser.parse(resp.text)
            entries = feed.get("entries", [])
            if not entries:
                break

            page_docs = []
            oldest_on_page: date | None = None
            for entry in entries:
                doc = _entry_to_document(entry)
                if doc is None:
                    continue
                if oldest_on_page is None or doc.published_date < oldest_on_page:
                    oldest_on_page = doc.published_date
                if client_side_filter:
                    if doc.published_date < date_from:
                        continue
                    if doc.published_date > date_to:
                        continue
                page_docs.append(doc)

            docs.extend(page_docs)
            logger.info(
                "arXiv: fetched %d entries (offset %d, total so far: %d)",
                len(entries), start, len(docs),
            )

            # Stop paginating once results have passed the start of our window.
            if client_side_filter and oldest_on_page is not None and oldest_on_page < date_from:
                logger.info(
                    "arXiv: oldest entry on page (%s) is before date_from (%s)"
                    " — stopping pagination",
                    oldest_on_page, date_from,
                )
                break

            if len(entries) < _PAGE_SIZE:
                break

            start += _PAGE_SIZE
            time.sleep(_RETRY_DELAY)

        if len(docs) >= _MAX_RESULTS:
            logger.warning(
                "arXiv: hit _MAX_RESULTS cap (%d); narrow the date range "
                "or keyword for more targeted results",
                _MAX_RESULTS,
            )

        logger.info("arXiv: %d documents in date range", len(docs))
        return docs


def _fetch_page_with_retry(
    search_query: str,
    start: int,
) -> requests.Response | None:
    """Fetch one page from arXiv, retrying on 429 with exponential backoff.

    Returns the response on success, or None after all retries are exhausted.
    """
    delay = _BACKOFF_BASE
    for attempt in range(_MAX_RETRIES):
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
            return resp
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 429:
                if attempt < _MAX_RETRIES - 1:
                    logger.warning(
                        "arXiv 429 at offset %d; retrying in %.0fs "
                        "(attempt %d/%d)",
                        start, delay, attempt + 1, _MAX_RETRIES,
                    )
                    time.sleep(delay)
                    delay *= 2
                    continue
            logger.exception(
                "arXiv API request failed at offset %d", start
            )
            return None
        except Exception:
            logger.exception(
                "arXiv API request failed at offset %d", start
            )
            return None
    logger.error(
        "arXiv: exhausted %d retries at offset %d", _MAX_RETRIES, start
    )
    return None


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
