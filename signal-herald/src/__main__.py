"""Entry point for signal-herald: serve (FastAPI) and run (one-shot)."""
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
    """signal-herald CLI."""


@cli.command()
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8006, show_default=True)
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
@click.option(
    "--job-id",
    default=None,
    type=int,
    help="Skip pipeline trigger; use this existing job_id directly.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Always trigger a fresh pipeline run, ignoring today's cached job.",
)
def run_digest(job_id: int | None, force: bool) -> None:
    """Run the one-shot daily digest pipeline (cron mode)."""
    if job_id is not None:
        from controllers.digest import _build_and_send

        _build_and_send(job_id)
    else:
        from controllers.digest import run_digest_polling

        run_digest_polling(force=force)


if __name__ == "__main__":
    cli()
