"""GDELT 2.0 Doc API adapter for historical news ingestion."""
import logging
from datetime import date

import requests
import trafilatura

from historical_ingestion.adapters.base import AbstractHistoricalAdapter
from historical_ingestion.schema import HistoricalDocument

logger = logging.getLogger(__name__)

_GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"
_MAX_RECORDS = 250


class GDELTAdapter(AbstractHistoricalAdapter):
    """Fetches news articles from the GDELT 2.0 Document API.

    The API returns at most 250 results per call. For larger date ranges,
    narrow the query or split the range into smaller windows.
    """

    def fetch(
        self,
        query: str,
        date_from: date,
        date_to: date,
    ) -> list[HistoricalDocument]:
        """Return up to 250 articles matching *query* in the date range."""
        start = date_from.strftime("%Y%m%d") + "000000"
        end = date_to.strftime("%Y%m%d") + "235959"

        try:
            resp = requests.get(
                _GDELT_API,
                params={
                    "query": query,
                    "mode": "artlist",
                    "format": "json",
                    "startdatetime": start,
                    "enddatetime": end,
                    "maxrecords": _MAX_RECORDS,
                },
                timeout=30,
            )
            resp.raise_for_status()
            text = resp.text.strip()
            if not text:
                logger.info("GDELT returned no results")
                return []
            if not resp.headers.get("content-type", "").startswith(
                "application/json"
            ):
                logger.error("GDELT API error: %s", text)
                return []
            data = resp.json()
        except Exception:
            logger.exception("GDELT API request failed")
            return []

        articles = data.get("articles") or []
        logger.info("GDELT returned %d article candidates", len(articles))

        docs: list[HistoricalDocument] = []
        for article in articles:
            url = article.get("url", "").strip()
            title = article.get("title", "").strip()
            seendate = article.get("seendate", "")

            if not url or not title:
                continue

            published = _parse_gdelt_date(seendate, date_from)
            body = _extract_body(url)
            if not body:
                logger.warning("No body extracted for %s — skipping", url)
                continue

            docs.append(
                HistoricalDocument(
                    url=url,
                    title=title,
                    body=body,
                    source_type="news",
                    published_date=published,
                    source_adapter="gdelt",
                    metadata={"domain": article.get("domain", "")},
                )
            )

        logger.info("GDELT: %d documents with extractable body", len(docs))
        return docs


def _parse_gdelt_date(seendate: str, fallback: date) -> date:
    """Parse GDELT seendate (YYYYMMDDTHHMMSSZ) into a date."""
    try:
        return date(int(seendate[:4]), int(seendate[4:6]), int(seendate[6:8]))
    except Exception:
        return fallback


def _extract_body(url: str) -> str | None:
    """Fetch and extract article body text using trafilatura."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded is None:
            return None
        return trafilatura.extract(downloaded) or None
    except Exception:
        logger.debug("trafilatura failed for %s", url, exc_info=True)
        return None
