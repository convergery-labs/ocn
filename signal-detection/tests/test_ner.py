"""Unit tests for the spaCy NER concept-extraction pipeline (CON-148).

No DB, no network, no mocks - tests call extract_concepts() directly.
Requires en_core_web_lg to be installed: python -m spacy download en_core_web_lg
"""

from pipeline.ner import extract_concepts


class TestExtractConcepts:
    """Tests for extract_concepts()."""

    def test_two_distinct_concepts_matched(self) -> None:
        """Article mentioning LLMs and drug discovery returns both slugs."""
        text = (
            "Researchers used a large language model to accelerate drug "
            "discovery, identifying candidate molecules 10x faster than "
            "traditional pharmaceutical screening methods."
        )
        result = extract_concepts(text)
        assert "large-language-models" in result
        assert "drug-discovery" in result

    def test_no_match_returns_empty_list(self) -> None:
        """Article with no domain keywords returns an empty list, no exception."""
        text = (
            "The weather today is sunny with a high of 72 degrees. "
            "Local farmers markets open at 8am."
        )
        result = extract_concepts(text)
        assert result == []

    def test_duplicate_mentions_deduplicated(self) -> None:
        """Multiple mentions of the same concept collapse to one slug."""
        text = (
            "GPT is a large language model. The LLM was trained on a large "
            "language model corpus. GPT-4 is the latest large language model "
            "from OpenAI. Language models like GPT have transformed NLP."
        )
        result = extract_concepts(text)
        assert result.count("large-language-models") == 1
