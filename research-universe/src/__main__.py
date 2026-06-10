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


@users.command("set-password")
@click.option("--email", prompt="Email", help="User's email address")
@click.password_option(help="Password to set")
def users_set_password(email: str, password: str) -> None:
    """Set or reset a password for a user (enables email/password login)."""
    import db
    import models.user as user_model
    db.init_db()
    user = user_model.get_by_email(email)
    if not user:
        click.echo(f"  Error: no active user found with email {email}", err=True)
        sys.exit(1)
    user_model.set_password(user["id"], password)
    click.echo(f"\n  Password set for {user['name']} <{email}>")
    click.echo("  They can now log in at the UI with their email and password.\n")


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


@cli.command("bulk-import")
@click.argument("json_file")
@click.option("--dry-run", is_flag=True, default=False, help="Print what would be inserted without writing to DB")
def bulk_import_cmd(json_file: str, dry_run: bool) -> None:
    """Bulk import companies from a JSON file (output of excel cross-reference).

    JSON must be a list of objects with keys: Company, Ticker, Market, Country,
    Website, Category, Subcategory.
    """
    import json as _json
    import db
    from db import get_db

    db.init_db()

    with open(json_file) as f:
        companies = _json.load(f)

    click.echo(f"Loaded {len(companies)} companies from {json_file}")

    # Load taxonomy
    cat_map: dict[str, int] = {}
    sub_map: dict[tuple, int] = {}
    with get_db() as conn:
        for row in conn.execute("SELECT id, name FROM universe_taxonomy WHERE type='category'").fetchall():
            cat_map[row["name"].strip()] = row["id"]
        for row in conn.execute("SELECT id, name, parent_id FROM universe_taxonomy WHERE type='subcategory'").fetchall():
            sub_map[(row["name"].strip(), row["parent_id"])] = row["id"]

    # Pre-fetch existing names + tickers for dedup
    with get_db() as conn:
        rows = conn.execute(
            "SELECT LOWER(company_name) AS n, LOWER(COALESCE(ticker,'')) AS t FROM universe_companies"
        ).fetchall()
    existing_names   = {r["n"] for r in rows}
    existing_tickers = {r["t"] for r in rows if r["t"] and r["t"] not in ("", "private")}

    inserted = skipped_dup = skipped_no_cat = 0
    errors: list[str] = []

    for c in companies:
        name     = (c.get("Company") or "").strip()
        ticker   = (c.get("Ticker") or "").strip()
        market   = (c.get("Market") or "").strip()
        country  = (c.get("Country") or "").strip()
        website  = (c.get("Website") or "").strip()
        cat_name = (c.get("Category") or "").strip()
        sub_name = (c.get("Subcategory") or "").strip()

        if not name:
            continue

        if name.lower() in existing_names:
            skipped_dup += 1
            continue
        if ticker and ticker.lower() not in ("", "private") and ticker.lower() in existing_tickers:
            skipped_dup += 1
            continue

        cat_id = cat_map.get(cat_name)
        if not cat_id:
            for k, v in cat_map.items():
                if cat_name.lower() in k.lower() or k.lower() in cat_name.lower():
                    cat_id = v
                    break
        if not cat_id:
            skipped_no_cat += 1
            errors.append(f"NO_CAT: {name} | {cat_name}")
            continue

        sub_id = sub_map.get((sub_name, cat_id))
        if not sub_id:
            for (sn, pid), sid in sub_map.items():
                if pid == cat_id and sn.lower() == sub_name.lower():
                    sub_id = sid
                    break

        if dry_run:
            click.echo(f"  DRY-RUN: {name} | {ticker} | cat={cat_id} sub={sub_id}")
            inserted += 1
            continue

        try:
            with get_db() as conn:
                conn.execute(
                    """
                    INSERT INTO universe_companies (
                        company_name, ticker, market, country, website,
                        category_ids, subcategory_ids,
                        status, agent_added, added_by
                    ) VALUES (
                        :company_name, :ticker, :market, :country, :website,
                        :category_ids, :subcategory_ids,
                        'pending_review', TRUE, 'bulk_import'
                    )
                    ON CONFLICT (company_name) DO NOTHING
                    """,
                    {
                        "company_name": name,
                        "ticker": ticker or None,
                        "market": market or None,
                        "country": country or None,
                        "website": website or None,
                        "category_ids": [cat_id],
                        "subcategory_ids": [sub_id] if sub_id else [],
                    },
                )
            existing_names.add(name.lower())
            if ticker and ticker.lower() not in ("", "private"):
                existing_tickers.add(ticker.lower())
            inserted += 1
            if inserted % 50 == 0:
                click.echo(f"  Inserted {inserted}...")
        except Exception as exc:
            errors.append(f"ERROR: {name} — {exc}")

    click.echo(f"\n=== {'DRY RUN ' if dry_run else ''}DONE ===")
    click.echo(f"Inserted      : {inserted}")
    click.echo(f"Skipped (dup) : {skipped_dup}")
    click.echo(f"Skipped (no cat): {skipped_no_cat}")
    if errors:
        click.echo(f"\nErrors/warnings ({len(errors)}):")
        for e in errors[:30]:
            click.echo(f"  {e}")


if __name__ == "__main__":
    cli()
