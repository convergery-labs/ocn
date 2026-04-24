"""Entry point for the signal-detection service."""
import logging

import click
import uvicorn

from db import init_db
from seed import seed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@click.group()
def cli() -> None:
    """signal-detection service CLI."""


@cli.command()
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8002)
def serve(host: str, port: int) -> None:
    """Start the uvicorn server."""
    from app import app

    logger.info("Initialising database...")
    init_db()
    logger.info("Seeding database...")
    seed()
    logger.info("Startup complete.")
    uvicorn.run(app, host=host, port=port)


@cli.command()
@click.option("--domain", required=True, help="Domain slug to bootstrap.")
@click.option(
    "--days-back",
    default=180,
    show_default=True,
    help="Number of days of historical articles to fetch.",
)
@click.option(
    "--k",
    default=8,
    show_default=True,
    help="Number of topic clusters (k-means k).",
)
def bootstrap(domain: str, days_back: int, k: int) -> None:
    """Embed and cluster historical articles to seed the corpus."""
    from controllers.bootstrap import run_bootstrap

    logger.info("Initialising database...")
    init_db()
    run_bootstrap(domain=domain, days_back=days_back, k=k)


@cli.command("promote-corpus")
def promote_corpus() -> None:
    """Process deferred corpus promotions (nightly job)."""
    from controllers.promote import promote_deferred_corpus

    logger.info("Initialising database...")
    init_db()
    stats = promote_deferred_corpus()
    logger.info("promote-corpus complete: %s", stats)


@cli.command("historical-ingest")
@click.option(
    "--adapter",
    required=True,
    type=click.Choice(["gdelt", "arxiv"]),
    help="Historical source adapter to use.",
)
@click.option("--query", required=True, help="Keyword or phrase to search for.")
@click.option(
    "--from",
    "date_from",
    required=True,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Inclusive start date (YYYY-MM-DD).",
)
@click.option(
    "--to",
    "date_to",
    required=True,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Inclusive end date (YYYY-MM-DD).",
)
@click.option(
    "--collection",
    default=None,
    help="Qdrant collection name (default: historical_{adapter}).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show document count without embedding or upserting.",
)
def historical_ingest(
    adapter: str,
    query: str,
    date_from: object,
    date_to: object,
    collection: str | None,
    dry_run: bool,
) -> None:
    """Ingest historical documents from GDELT or arXiv into Qdrant."""
    from historical_ingestion.adapters.arxiv import ArXivAdapter
    from historical_ingestion.adapters.gdelt import GDELTAdapter
    from historical_ingestion.pipeline import run_ingestion

    adapter_map = {"gdelt": GDELTAdapter(), "arxiv": ArXivAdapter()}
    col = collection or f"historical_{adapter}"
    stats = run_ingestion(
        adapter=adapter_map[adapter],
        query=query,
        date_from=date_from.date(),  # type: ignore[union-attr]
        date_to=date_to.date(),      # type: ignore[union-attr]
        collection=col,
        dry_run=dry_run,
    )
    logger.info("historical-ingest complete: %s", stats)


if __name__ == "__main__":
    cli()
