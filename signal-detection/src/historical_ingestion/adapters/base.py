"""Abstract base class for all historical source adapters."""
from abc import ABC, abstractmethod
from datetime import date

from historical_ingestion.schema import HistoricalDocument


class AbstractHistoricalAdapter(ABC):
    """Interface that every historical source adapter must implement."""

    @abstractmethod
    def fetch(
        self,
        query: str,
        date_from: date,
        date_to: date,
    ) -> list[HistoricalDocument]:
        """Fetch documents matching *query* within the given date range.

        Args:
            query: Keyword or phrase to search for.
            date_from: Inclusive start date.
            date_to: Inclusive end date.

        Returns:
            List of normalised HistoricalDocument instances.
        """
