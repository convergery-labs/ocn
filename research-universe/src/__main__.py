"""Entry point for research-universe: serve, run, init-sheet."""
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
    """research-universe CLI."""


@cli.command()
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8006, show_default=True)
@click.option("--reload", is_flag=True, default=False)
def serve(host: str, port: int, reload: bool) -> None:
    """Run the FastAPI server."""
    uvicorn.run(
        "app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
    )


@cli.command("run")
def run_pipeline() -> None:
    """Run the full discovery pipeline (implemented in Phase 6)."""
    raise NotImplementedError("Pipeline not yet implemented — see Phase 6")


@cli.command("init-sheet")
@click.option(
    "--file",
    "xlsx_path",
    required=True,
    type=click.Path(exists=True),
    help="Path to the AlphaStreet XLSX file",
)
def init_sheet(xlsx_path: str) -> None:
    """Create Google Sheet from XLSX and print the sheet ID."""
    from sheets.init import run_init_sheet

    sheet_id = run_init_sheet(xlsx_path)
    click.echo(f"GOOGLE_SHEET_ID={sheet_id}")


if __name__ == "__main__":
    cli()
