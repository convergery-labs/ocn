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
    from models.company import normalize_country

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
        country  = normalize_country((c.get("Country") or "").strip())
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


@cli.command("load-market-universe")
@click.argument("json_file")
@click.option("--dry-run", is_flag=True, default=False,
              help="Report what would change without writing.")
def load_market_universe_cmd(json_file: str, dry_run: bool) -> None:
    """Load or refresh one country's tracked companies and their customers.

    Unlike ``bulk-import``, which only inserts and skips anything that
    already exists, this ENRICHES: most of these companies are already in
    the universe, curated by hand, and what they lack is the market
    profile the signal pipelines need - local code, local name, fiscal
    calendar, aliases. So a company that is already here is updated in
    place rather than skipped.

    Matched on (country, local_code), never on name: a name is editable,
    and keying on one creates a duplicate the first time someone fixes a
    spelling. Rows that predate this loader have no local_code, so they
    are found by name ONCE and stamped with their code; every run after
    that matches on the code.

    Curated fields are never overwritten. An existing row keeps its
    category, website and status - the catalogue's editorial decisions
    are not this loader's to revise. Only the market-profile columns,
    which no human curated, are written.
    """
    import json as _json

    import db
    from db import get_db
    from models.company import normalize_country

    db.init_db()

    with open(json_file) as f:
        payload = _json.load(f)

    # Rows whose stored name differs from the pipeline's. Spelled out one
    # by one rather than fuzzy-matched: several of these companies have a
    # near-namesake in the catalogue already - SoftBank Group sits beside
    # SoftBank Corp (its subsidiary) and an ADR line, and Renesas appears
    # twice - so a similarity match would silently enrich the wrong row
    # and leave the right one to be created as a duplicate. An entry here
    # is a deliberate statement that two names are one company; anything
    # not listed must match exactly or be created.
    name_overrides: dict[str, str] = {
        o["local_code"]: o["stored_as"]
        for o in payload.get("name_overrides", [])
    }

    country = normalize_country(payload["country"])
    companies = payload["companies"]
    click.echo(f"{json_file}: {len(companies)} companies, "
               f"{sum(len(c['customers']) for c in companies)} customers "
               f"({country})")

    # Taxonomy, needed only for rows we have to create.
    cat_map: dict[str, int] = {}
    sub_map: dict[tuple[str, int], int] = {}
    with get_db() as conn:
        for r in conn.execute(
                "SELECT id, name FROM universe_taxonomy WHERE type='category'"
        ).fetchall():
            cat_map[r["name"].strip()] = r["id"]
        for r in conn.execute(
                "SELECT id, name, parent_id FROM universe_taxonomy "
                "WHERE type='subcategory'").fetchall():
            sub_map[(r["name"].strip(), r["parent_id"])] = r["id"]

    created = enriched = cust_rows = 0
    fixed: list[str] = []
    errors: list[str] = []

    for c in companies:
        code, name = c["local_code"], c["company_name"]
        match_name = name_overrides.get(code, name)
        try:
            with get_db() as conn:
                row = conn.execute(
                    "SELECT id::text, company_name, ticker, country, market "
                    "FROM universe_companies "
                    " WHERE (country = :country AND local_code = :code) "
                    "    OR LOWER(company_name) = LOWER(:match_name)",
                    {"country": country, "code": code,
                     "match_name": match_name},
                ).fetchone()

                if row is None:
                    cat_id = cat_map.get(c["category"] or "")
                    sub_id = sub_map.get((c["subcategory"] or "", cat_id or -1))
                    if not cat_id:
                        errors.append(f"{code} {name}: category "
                                      f"{c['category']!r} not in taxonomy")
                        continue
                    if dry_run:
                        click.echo(f"  CREATE  {code}  {name}")
                        created += 1
                        continue
                    cur = conn.execute(
                        """
                        INSERT INTO universe_companies (
                            company_name, ticker, market, country, website,
                            category_ids, subcategory_ids,
                            status, agent_added, added_by
                        ) VALUES (
                            :name, :ticker, :market, :country, :website,
                            :cats, :subs,
                            'verified', FALSE, 'load-market-universe'
                        ) RETURNING id::text
                        """,
                        {"name": name, "ticker": c["ticker"],
                         "market": c["market"], "country": country,
                         "website": c["website"], "cats": [cat_id],
                         "subs": [sub_id] if sub_id else []},
                    )
                    company_id = cur.fetchone()["id"]
                    created += 1
                else:
                    company_id = row["id"]
                    # An ADR ticker on a row whose country is also wrong is
                    # a mis-add, not a deliberate choice of listing: the
                    # company is Japanese either way. Corrected, and said
                    # out loud rather than silently.
                    if row["country"] != country:
                        fixed.append(f"{code} {name}: country "
                                     f"{row['country']} -> {country}, "
                                     f"ticker {row['ticker']} -> {c['ticker']}")
                        if not dry_run:
                            conn.execute(
                                "UPDATE universe_companies "
                                "   SET country = :country, market = :market, "
                                "       ticker = :ticker "
                                " WHERE id = :id",
                                {"country": country, "market": c["market"],
                                 "ticker": c["ticker"], "id": company_id},
                            )
                    # The registered company name. The catalogue and the
                    # pipelines disagreed on four of these - one said
                    # "Murata", the other "Murata Manufacturing"; one
                    # "Kioxia", the other "Kioxia Holdings" - and a
                    # company name is not a cosmetic field here: it is
                    # what an English-language news search is run on, so
                    # the shorter form silently returns fewer articles.
                    # The file carries the decided name and it wins.
                    if row["company_name"] != name:
                        fixed.append(f"{code}: name "
                                     f"{row['company_name']!r} -> {name!r}")
                        if not dry_run:
                            conn.execute(
                                "UPDATE universe_companies "
                                "   SET company_name = :name WHERE id = :id",
                                {"name": name, "id": company_id},
                            )
                    enriched += 1
                    if dry_run:
                        click.echo(f"  ENRICH  {code}  {name}")

                if dry_run:
                    cust_rows += len(c["customers"])
                    continue

                conn.execute(
                    """
                    UPDATE universe_companies SET
                        local_code         = :code,
                        local_name         = :local_name,
                        search_query       = :search_query,
                        aliases            = :aliases,
                        exclude_terms      = :exclude_terms,
                        fiscal_year_end    = :fiscal_year_end,
                        market_cap_usd_bn  = :market_cap_usd_bn,
                        market_cap_local   = :market_cap_local,
                        local_currency     = :local_currency,
                        index_name         = :index_name,
                        index_weight_pct   = :index_weight_pct,
                        home_market_rank   = :home_market_rank,
                        domestic_sales_pct = :domestic_sales_pct,
                        financials_period  = :financials_period,
                        market_data_as_of  = :market_data_as_of
                      WHERE id = :id
                    """,
                    {**{k: c[k] for k in (
                        "local_name", "search_query", "aliases", "exclude_terms",
                        "fiscal_year_end", "market_cap_usd_bn",
                        "market_cap_local", "local_currency", "index_name",
                        "index_weight_pct", "home_market_rank",
                        "domestic_sales_pct", "financials_period",
                        "market_data_as_of")},
                     "code": code, "id": company_id},
                )

                # Replaced wholesale: the source file is the record, so a
                # customer dropped from it should disappear here too. An
                # upsert would leave the stale row behind for good.
                conn.execute(
                    "DELETE FROM universe_company_customers "
                    " WHERE company_id = :id", {"id": company_id})
                for cust in c["customers"]:
                    conn.execute(
                        """
                        INSERT INTO universe_company_customers (
                            company_id, customer_name, customer_ticker,
                            aliases, relationship, pct_of_sales, period
                        ) VALUES (
                            :id, :customer_name, :customer_ticker,
                            :aliases, :relationship, :pct_of_sales, :period
                        )
                        """,
                        {**cust, "id": company_id},
                    )
                    cust_rows += 1
        except Exception as exc:                      # noqa: BLE001
            errors.append(f"{code} {name}: {exc}")

    click.echo(f"\n=== {'DRY RUN ' if dry_run else ''}DONE ===")
    click.echo(f"Created  : {created}")
    click.echo(f"Enriched : {enriched}")
    click.echo(f"Customers: {cust_rows}")
    if fixed:
        click.echo(f"\nCorrected ({len(fixed)}):")
        for f in fixed:
            click.echo(f"  {f}")
    if errors:
        click.echo(f"\nErrors ({len(errors)}):")
        for e in errors:
            click.echo(f"  {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    cli()
