"""Tests for historical-ingest CLI collection name routing."""
import importlib.util
import os
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

_spec = importlib.util.spec_from_file_location(
    "_signal_main",
    os.path.join(os.path.dirname(__file__), "..", "src", "__main__.py"),
)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
cli = _mod.cli


def _base_args(extra: list[str] | None = None) -> list[str]:
    """Return a minimal valid historical-ingest invocation."""
    args = [
        "historical-ingest",
        "--adapter", "gdelt",
        "--query", "test",
        "--from", "2024-01-01",
        "--to", "2024-01-02",
        "--domain", "ai_news",
    ]
    return args + (extra or [])


def _invoke(args: list[str]) -> tuple[object, MagicMock]:
    """Run the CLI and return the result and the run_ingestion mock."""
    runner = CliRunner()
    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = []
    with (
        patch(
            "historical_ingestion.pipeline.run_ingestion",
            return_value={"fetched": 0, "new": 0, "upserted": 0},
        ) as mock_run,
        patch(
            "historical_ingestion.adapters.gdelt.GDELTAdapter",
            return_value=mock_adapter,
        ),
        patch(
            "historical_ingestion.adapters.arxiv.ArXivAdapter",
            return_value=mock_adapter,
        ),
    ):
        result = runner.invoke(cli, args)
    return result, mock_run


def test_domain_routes_to_bootstrap_collection() -> None:
    """--domain ai_news writes to bootstrap_ai_news."""
    result, mock_run = _invoke(_base_args())
    assert result.exit_code == 0, result.output
    _, kwargs = mock_run.call_args
    assert kwargs["collection"] == "bootstrap_ai_news"


def test_collection_override_takes_priority_over_domain() -> None:
    """--collection custom overrides --domain."""
    result, mock_run = _invoke(
        _base_args(["--collection", "custom_collection"])
    )
    assert result.exit_code == 0, result.output
    _, kwargs = mock_run.call_args
    assert kwargs["collection"] == "custom_collection"


def test_missing_domain_exits_with_error() -> None:
    """Omitting --domain causes a non-zero exit (Click required flag)."""
    runner = CliRunner()
    result = runner.invoke(cli, [
        "historical-ingest",
        "--adapter", "gdelt",
        "--query", "test",
        "--from", "2024-01-01",
        "--to", "2024-01-02",
    ])
    assert result.exit_code != 0
    assert "domain" in result.output.lower()
