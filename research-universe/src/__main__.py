"""Entry point for research-universe."""
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
@click.option("--port", default=8007, show_default=True)
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


@cli.group()
def users() -> None:
    """Manage users and API keys."""


@users.command("create")
@click.option("--name", prompt="Full name", help="User's display name")
@click.option("--email", prompt="Email", help="User's email address")
def users_create(name: str, email: str) -> None:
    """Create a new user and print their API key."""
    import db
    import models.user as user_model
    db.init_db()
    try:
        user, raw_key = user_model.create(name, email)
        click.echo("")
        click.echo(f"  User created: {user['name']} <{user['email']}>")
        click.echo(f"  ID:           {user['id']}")
        click.echo("")
        click.echo(f"  API Key:      {raw_key}")
        click.echo("")
        click.echo("  ⚠️  Store this key securely - it cannot be retrieved again.")
        click.echo("      Share it with the user and ask them to add it to Lovable.")
        click.echo("")
    except Exception as exc:
        if "unique" in str(exc).lower():
            click.echo(f"  Error: a user with email {email} already exists.", err=True)
        else:
            click.echo(f"  Error: {exc}", err=True)
        sys.exit(1)


@users.command("list")
def users_list() -> None:
    """List all users."""
    import db
    import models.user as user_model
    db.init_db()
    all_users = user_model.get_all()
    if not all_users:
        click.echo("No users yet. Run: python -m src users create")
        return
    click.echo(f"\n{'Name':<20} {'Email':<30} {'Active':<8} {'Last seen'}")
    click.echo("-" * 75)
    for u in all_users:
        active = "✓" if u["is_active"] else "✗"
        seen = str(u.get("last_seen_at") or "never")[:19]
        click.echo(f"{u['name']:<20} {u['email']:<30} {active:<8} {seen}")
    click.echo("")


@cli.command("scan-all")
def scan_all_cmd() -> None:
    """Scan all 19 categories. Called by CloudWatch twice a week (Mon + Thu)."""
    import db
    import models.scan_job as scan_job_model
    import models.taxonomy as taxonomy_model
    from agent.discovery import run_scan

    db.init_db()

    cats = taxonomy_model.list_categories()
    if not cats:
        click.echo("No categories found.")
        return

    category_ids = [c["id"] for c in cats]
    click.echo(f"Starting full scan - {len(category_ids)} categories")
    job_id = scan_job_model.create(category_ids, "scheduler")
    run_scan(job_id, category_ids, "scheduler")

    job = scan_job_model.get(job_id)
    click.echo(
        f"Done - proposed={job['companies_proposed']} skipped={job['companies_skipped']}"
    )


@users.command("rotate")
@click.argument("user_id")
def users_rotate(user_id: str) -> None:
    """Rotate API key for a user (old key revoked immediately)."""
    import db
    import models.user as user_model
    db.init_db()
    new_key = user_model.rotate_key(user_id)
    click.echo(f"\n  New API Key: {new_key}")
    click.echo("  Old key is now invalid.\n")


if __name__ == "__main__":
    cli()
