"""Entry point for lucky-clarke: serve (FastAPI) and run (one-shot)."""
import logging
import sys

import click
import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)


@click.group()
def cli() -> None:
    """lucky-clarke CLI."""


@cli.command()
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8005, show_default=True)
@click.option("--reload", is_flag=True, default=False)
def serve(host: str, port: int, reload: bool) -> None:
    """Run the A2A FastAPI server."""
    uvicorn.run(
        "app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
    )


@cli.command("run")
def run_digest() -> None:
    """Run the one-shot daily digest pipeline (cron mode)."""
    from controllers.digest import run_digest_polling

    run_digest_polling()


if __name__ == "__main__":
    cli()
