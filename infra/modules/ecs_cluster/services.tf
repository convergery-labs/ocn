resource "aws_ecs_task_definition" "auth_service" {
  family                   = "${var.env}-auth-service"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn


  container_definitions = jsonencode([
    {
      name  = "auth-service"
      image = "${var.ecr_registry}/ocn/auth-service:${var.image_tag}"
      portMappings = [
        { containerPort = 8001 }
      ]
      environment = [
        { name = "AUTH_POSTGRES_HOST",       value = var.rds_endpoint },
        { name = "AUTH_POSTGRES_PORT",       value = "5432" },
        { name = "AUTH_POSTGRES_DB",         value = "auth_db" },
        { name = "AUTH_POSTGRES_USER",       value = "auth_user" },
        { name = "PGSSLMODE",                value = "require" },
        { name = "AUTH_JWT_EXPIRY_SECONDS",  value = "86400" }
      ]
      secrets = [
        {
          name      = "AUTH_POSTGRES_PASSWORD"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/auth-service:POSTGRES_PASSWORD::"
        },
        {
          name      = "AUTH_ADMIN_API_KEY"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/auth-service:ADMIN_API_KEY::"
        },
        {
          name      = "AUTH_JWT_PRIVATE_KEY"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/auth-service:JWT_PRIVATE_KEY::"
        },
        {
          name      = "ADMIN_USERNAME"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/auth-service:ADMIN_USERNAME::"
        },
        {
          name      = "ADMIN_EMAIL"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/auth-service:ADMIN_EMAIL::"
        },
        {
          name      = "ADMIN_PASSWORD"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/auth-service:ADMIN_PASSWORD::"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/${var.env}/auth-service"
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])

  lifecycle {
    ignore_changes = [container_definitions]
  }
}


resource "aws_service_discovery_service" "auth_service" {
  name = "auth-service"
  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id
    dns_records {
      ttl  = 10
      type = "A"
    }
  }
}


resource "aws_ecs_service" "auth_service" {
  name            = "${var.env}-auth-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.auth_service.arn
  desired_count   = 1
  launch_type     = "FARGATE"


  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.auth_sg_id]
    assign_public_ip = false
  }


  service_registries {
    registry_arn = aws_service_discovery_service.auth_service.arn
  }

  lifecycle {
    ignore_changes = [task_definition]
  }
}

resource "aws_ecs_task_definition" "news_retrieval" {
  family                   = "${var.env}-news-retrieval"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task_exec_ssm.arn

  container_definitions = jsonencode([
    {
      name  = "news-retrieval"
      image = "${var.ecr_registry}/ocn/news-retrieval:${var.image_tag}"
      portMappings = [
        { containerPort = 8000 }
      ]
      environment = [
        { name = "POSTGRES_HOST",    value = var.rds_endpoint },
        { name = "POSTGRES_PORT",    value = "5432" },
        { name = "POSTGRES_DB",      value = "news_retrieval_db" },
        { name = "POSTGRES_USER",    value = "news_user" },
        { name = "PGSSLMODE",        value = "require" },
        { name = "AUTH_SERVICE_URL",        value = "http://auth-service.${var.env}.ocn.internal:8001" },
        { name = "NEWS_RETRIEVAL_URL",      value = "http://news-retrieval.${var.env}.ocn.internal:8000" },
        { name = "RESEARCH_UNIVERSE_URL",   value = "http://research-universe.${var.env}.ocn.internal:8007" },
        { name = "AWS_REGION",                    value = var.aws_region },
        { name = "DYNAMODB_TABLE_QUOTE",          value = "ocn-market-quote" },
        { name = "DYNAMODB_TABLE_OVERVIEW",       value = "ocn-market-overview" },
        { name = "DYNAMODB_TABLE_PRICE_HISTORY",  value = "ocn-market-price-history" },
        { name = "DYNAMODB_TABLE_EARNINGS",       value = "ocn-market-earnings" },
        { name = "DYNAMODB_TABLE_INDICES",        value = "ocn-market-indices" },
        { name = "DYNAMODB_TABLE_MARKET_STATUS",  value = "ocn-market-status" },
        { name = "DYNAMODB_TABLE_LOCK",           value = "ocn-market-lock" },
        { name = "DYNAMODB_TABLE_SEC_FILINGS",    value = "ocn-sec-filings" },
        { name = "DYNAMODB_TABLE_MACRO",          value = "ocn-market-macro" }
      ]
      secrets = [
        {
          name      = "POSTGRES_PASSWORD"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/news-retrieval:POSTGRES_PASSWORD::"
        },
        {
          name      = "OPENROUTER_API_KEY"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/news-retrieval:OPENROUTER_API_KEY::"
        },
        {
          name      = "SERPAPI_KEY"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/news-retrieval:SERPAPI_KEY::"
        },
        {
          name      = "SERPAPI_KEY_GEOPOLITICAL"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/news-retrieval:SERPAPI_KEY_GEOPOLITICAL::"
        },
        {
          name      = "NEWSAPI_KEY"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/news-retrieval:NEWSAPI_KEY::"
        },
        {
          name      = "ALPHA_VANTAGE_API_KEY"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/news-retrieval:ALPHA_VANTAGE_API_KEY::"
        },
        {
          name      = "RESEARCH_UNIVERSE_API_KEY"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/news-retrieval:RESEARCH_UNIVERSE_API_KEY::"
        },
        {
          # Required for the dart_filing source_type (korea_market_signal
          # domain) - DART (Financial Supervisory Service) OpenAPI key,
          # free/self-service at opendart.fss.or.kr. Must exist in
          # Secrets Manager under this key before terraform apply, same
          # requirement as every other secret above (infra/CLAUDE.md).
          # The Korea Customs press-release scraper (kr_customs_export
          # source_type) needs no credential at all - no-login scrape.
          name      = "DART_API_KEY"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/news-retrieval:DART_API_KEY::"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/${var.env}/news-retrieval"
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])

  lifecycle {
    # task_role_arn is also ignored, not just container_definitions - it's a
    # sibling top-level attribute that Terraform's state has drifted on
    # (stuck pointing at ecs_task_execution while the live task now uses
    # ecs_task_exec_ssm for ECS exec support). Without this, a real
    # `terraform apply` would force-replace this task definition purely to
    # reconcile task_role_arn, rebuilding container_definitions from this
    # file's own template in the process - which bakes in image_tag's
    # unsafe "latest" default instead of the SHA-pinned image CI/CD
    # actually deployed. Same class of drift as container_definitions;
    # excluding it here closes that gap the same way.
    ignore_changes = [container_definitions, task_role_arn]
  }
}


resource "aws_service_discovery_service" "news_retrieval" {
  name = "news-retrieval"
  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id
    dns_records {
      ttl  = 10
      type = "A"
    }
  }
}


resource "aws_ecs_service" "news_retrieval" {
  name                   = "${var.env}-news-retrieval"
  cluster                = aws_ecs_cluster.main.id
  task_definition        = aws_ecs_task_definition.news_retrieval.arn
  desired_count          = 1
  launch_type            = "FARGATE"
  enable_execute_command = true


  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.news_sg_id]
    assign_public_ip = false
  }


  service_registries {
    registry_arn = aws_service_discovery_service.news_retrieval.arn
  }

  lifecycle {
    ignore_changes = [task_definition]
  }
}

resource "aws_cloudwatch_event_rule" "news_retrieval_company_news_daily" {
  name                = "${var.env}-news-retrieval-company-news-daily"
  schedule_expression = "cron(0 1 * * ? *)"
}

resource "aws_cloudwatch_event_target" "news_retrieval_company_news_daily" {
  rule     = aws_cloudwatch_event_rule.news_retrieval_company_news_daily.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn

  ecs_target {
    # Family-only ARN (no revision suffix) - see comment on the daily fetch
    # target above for why this is unpinned rather than a specific revision.
    task_definition_arn = "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${aws_ecs_task_definition.news_retrieval.family}"
    launch_type         = "FARGATE"
    network_configuration {
      subnets          = var.public_subnet_ids
      security_groups  = [var.news_sg_id]
      assign_public_ip = true
    }
  }

  input = jsonencode({
    containerOverrides = [
      {
        name    = "news-retrieval"
        command = ["python", "__main__.py", "trigger", "--domain", "company_news", "--days-back", "1"]
      }
    ]
  })
}

resource "aws_cloudwatch_event_rule" "news_retrieval_geopolitical_news_daily" {
  name = "${var.env}-news-retrieval-geopolitical-news-daily"
  # Offset an hour after company_news (01:00 UTC) - geopolitical_news's GDELT
  # source runs 27 sequential theme queries with round-robin retries on rate
  # limiting, so it can take much longer than company_news's ticker fetch.
  schedule_expression = "cron(0 2 * * ? *)"
}

resource "aws_cloudwatch_event_target" "news_retrieval_geopolitical_news_daily" {
  rule     = aws_cloudwatch_event_rule.news_retrieval_geopolitical_news_daily.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn

  ecs_target {
    # Family-only ARN (no revision suffix) - CloudWatch resolves this to
    # whichever revision is currently ACTIVE at trigger time, so scheduled
    # runs never pin to a stale revision left behind in Terraform state
    # (this rule's target previously pinned revision 22 while the live
    # service had moved on to revision 38+, via CI/CD deploys outside TF).
    task_definition_arn = "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${aws_ecs_task_definition.news_retrieval.family}"
    launch_type         = "FARGATE"
    network_configuration {
      subnets          = var.public_subnet_ids
      security_groups  = [var.news_sg_id]
      assign_public_ip = true
    }
  }

  input = jsonencode({
    containerOverrides = [
      {
        name = "news-retrieval"
        # --callback-url: notify signal-detection-agent the moment this
        # fetch actually finishes, so its geopolitical_signal pipeline
        # starts immediately rather than waiting on a fixed-offset guess
        # (signal_detection_agent_geopolitical_signal_pipeline_daily below
        # still runs on its own 05:00 UTC schedule too, as a fallback for
        # if this webhook delivery is ever missed - see that rule's own
        # comment and routes/webhooks.py in signal-detection-agent).
        command = [
          "python", "__main__.py", "trigger",
          "--domain", "geopolitical_news", "--days-back", "1",
          "--callback-url", "http://signal-detection-agent.${var.env}.ocn.internal:8003/webhooks/news-retrieval-run-completed",
        ]
      }
    ]
  })
}

resource "aws_cloudwatch_event_rule" "news_retrieval_taiwan_market_signal" {
  name = "${var.env}-news-retrieval-taiwan-market-signal"
  # Every 4 hours, bounded to 01:00-16:00 UTC only (fires at 01,05,09,13
  # UTC), Mon-Fri (Taiwan has no weekend trading). The step must stay
  # bounded to this range, not "0/4" unbounded (which fires all 24 hours,
  # including well outside Taiwan trading/announcement hours - a mistake
  # caught before an earlier version of this schedule shipped). 01:00-05:30
  # UTC covers TWSE/TPEx's 9:00 AM-1:30 PM Taipei trading session; the
  # window extends through 16:00 UTC (midnight Taipei) because Taiwan's
  # 重大訊息 (material announcement) disclosures are confirmed to cluster
  # AFTER market close through the evening (5:30 PM Taipei / 09:30 UTC
  # onward), not during trading hours - a trading-hours-only window would
  # miss most of that feed. TWSE/TPEx's own full-dump endpoints have no
  # date/period query param (always return only the latest snapshot - see
  # pipeline.py's freshness check), so polling on a schedule + dedup on
  # ingest is the only way to capture each day's new revenue/announcement
  # rows; missing a day's poll window loses that day's data permanently,
  # there is no backfill - a 4-hour cadence (down from 30 min, then 2
  # hours) trades some of that margin for lower cost/load, on the
  # reasoning that revenue/material announcements don't need 30-minute
  # freshness the way a live price feed would.
  #
  # Does NOT account for Taiwan's own holiday calendar (e.g. multi-day
  # Lunar New Year closure), which is distinct from US holidays - on a
  # closed trading day this simply polls a market that isn't publishing
  # anything new, which is harmless (dedup prevents any duplicate
  # inserts) but not worth suppressing via a holiday-aware schedule for
  # this initial cut.
  schedule_expression = "cron(0 1-16/4 ? * MON-FRI *)"
}

resource "aws_cloudwatch_event_target" "news_retrieval_taiwan_market_signal" {
  rule     = aws_cloudwatch_event_rule.news_retrieval_taiwan_market_signal.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn

  ecs_target {
    # Family-only ARN (no revision suffix) - see comment on the daily fetch
    # target above for why this is unpinned rather than a specific revision.
    task_definition_arn = "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${aws_ecs_task_definition.news_retrieval.family}"
    launch_type         = "FARGATE"
    network_configuration {
      subnets          = var.public_subnet_ids
      security_groups  = [var.news_sg_id]
      assign_public_ip = true
    }
  }

  input = jsonencode({
    containerOverrides = [
      {
        name    = "news-retrieval"
        command = ["python", "__main__.py", "trigger", "--domain", "taiwan_market_signal", "--days-back", "1"]
      }
    ]
  })
}

resource "aws_cloudwatch_event_rule" "news_retrieval_korea_market_signal" {
  name = "${var.env}-news-retrieval-korea-market-signal"
  # Every 4 hours, unbounded across all 24 hours, all 7 days - unlike
  # Taiwan's schedule above, Korea's own sources don't concentrate in a
  # narrow trading-hours window. DART filings are lodged in the evening
  # KST and around weekend board meetings (KST is UTC+9, so Korea's own
  # business day runs roughly 23:00-14:00 UTC the previous calendar day);
  # the Korea Customs press-release scrape publishes at a fixed few-times-
  # a-month cadence (11th/21st/1st) with no time-of-day pattern to bound
  # around; RSS/GDELT news can break at any hour. A 4-hour, all-day, all-
  # week cadence matches the Korea Signals spec's own Step 2 instruction
  # ("Run from early morning to late evening, seven days a week") rather
  # than assuming a Taiwan-shaped trading session.
  #
  # DART's list.json IS date-range queryable (bgn_de/end_de), unlike
  # TWSE/TPEx's always-latest-snapshot endpoints - so a missed poll window
  # is recoverable on the next run (bounded by --days-back), not a
  # permanent gap the way Taiwan's revenue/material feed is. Still polled
  # on a schedule rather than backfilled after the fact, to keep same-day
  # freshness for time-sensitive items (S6 rumour-adjudication answers,
  # Tier 1 company filings) rather than relying on a later catch-up.
  schedule_expression = "cron(0 0/4 * * ? *)"
  # Paused 2026-09-23 (explicit request) - was previously disabled directly
  # via `aws events disable-rule`, which would have been silently reverted
  # by the next terraform apply touching this resource (state defaults to
  # ENABLED) - set here so the paused state actually persists through
  # Terraform. Set back to "ENABLED" (or remove this line) to resume.
  state = "DISABLED"
}

resource "aws_cloudwatch_event_target" "news_retrieval_korea_market_signal" {
  rule     = aws_cloudwatch_event_rule.news_retrieval_korea_market_signal.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn

  ecs_target {
    # Family-only ARN (no revision suffix) - see comment on the daily fetch
    # target above for why this is unpinned rather than a specific revision.
    task_definition_arn = "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${aws_ecs_task_definition.news_retrieval.family}"
    launch_type         = "FARGATE"
    network_configuration {
      subnets          = var.public_subnet_ids
      security_groups  = [var.news_sg_id]
      assign_public_ip = true
    }
  }

  input = jsonencode({
    containerOverrides = [
      {
        name    = "news-retrieval"
        command = ["python", "__main__.py", "trigger", "--domain", "korea_market_signal", "--days-back", "1"]
      }
    ]
  })
}

resource "aws_cloudwatch_event_rule" "news_retrieval_geopolitical_news_expire_weekly" {
  name = "${var.env}-news-retrieval-geopolitical-news-expire-weekly"
  # Sunday 04:00 UTC - 2 hours after the daily 02:00 UTC geopolitical_news
  # fetch, which typically completes by ~02:30-02:35 UTC, so this never
  # races with that day's ingest.
  schedule_expression = "cron(0 4 ? * SUN *)"
}

resource "aws_cloudwatch_event_target" "news_retrieval_geopolitical_news_expire_weekly" {
  rule     = aws_cloudwatch_event_rule.news_retrieval_geopolitical_news_expire_weekly.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn

  ecs_target {
    # Family-only ARN (no revision suffix) - see comment on the daily fetch
    # target above for why this is unpinned rather than a specific revision.
    task_definition_arn = "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${aws_ecs_task_definition.news_retrieval.family}"
    launch_type         = "FARGATE"
    network_configuration {
      subnets          = var.public_subnet_ids
      security_groups  = [var.news_sg_id]
      assign_public_ip = true
    }
  }

  input = jsonencode({
    containerOverrides = [
      {
        name    = "news-retrieval"
        command = ["python", "__main__.py", "expire-articles", "--domain", "geopolitical_news", "--days", "7"]
      }
    ]
  })
}

resource "aws_cloudwatch_event_rule" "news_retrieval_company_news_expire_weekly" {
  name = "${var.env}-news-retrieval-company-news-expire-weekly"
  # Sunday 05:00 UTC - after the daily 01:00 UTC company_news fetch and
  # after geopolitical_news's own 04:00 UTC expiry job, so neither cleanup
  # job overlaps with a fetch or with each other.
  schedule_expression = "cron(0 5 ? * SUN *)"
}

resource "aws_cloudwatch_event_target" "news_retrieval_company_news_expire_weekly" {
  rule     = aws_cloudwatch_event_rule.news_retrieval_company_news_expire_weekly.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn

  ecs_target {
    # Family-only ARN (no revision suffix) - see comment on the daily fetch
    # target above for why this is unpinned rather than a specific revision.
    task_definition_arn = "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${aws_ecs_task_definition.news_retrieval.family}"
    launch_type         = "FARGATE"
    network_configuration {
      subnets          = var.public_subnet_ids
      security_groups  = [var.news_sg_id]
      assign_public_ip = true
    }
  }

  input = jsonencode({
    containerOverrides = [
      {
        name    = "news-retrieval"
        # 30 days - matches the TTL already used for Alpha Vantage's other
        # data types (company overview, earnings) in DynamoDB, per poller.py.
        command = ["python", "__main__.py", "expire-articles", "--domain", "company_news", "--days", "30"]
      }
    ]
  })
}

resource "aws_cloudwatch_event_rule" "news_retrieval_vc_commentary_expire_weekly" {
  name = "${var.env}-news-retrieval-vc-commentary-expire-weekly"
  # Sunday 06:00 UTC - after the daily 03:00 UTC vc_commentary fetch and
  # after geopolitical_news (04:00 UTC) / company_news (05:00 UTC) expiry
  # jobs, so no two scheduled jobs overlap.
  schedule_expression = "cron(0 6 ? * SUN *)"
}

resource "aws_cloudwatch_event_target" "news_retrieval_vc_commentary_expire_weekly" {
  rule     = aws_cloudwatch_event_rule.news_retrieval_vc_commentary_expire_weekly.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn

  ecs_target {
    # Family-only ARN (no revision suffix) - see comment on the daily fetch
    # target above for why this is unpinned rather than a specific revision.
    task_definition_arn = "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${aws_ecs_task_definition.news_retrieval.family}"
    launch_type         = "FARGATE"
    network_configuration {
      subnets          = var.public_subnet_ids
      security_groups  = [var.news_sg_id]
      assign_public_ip = true
    }
  }

  input = jsonencode({
    containerOverrides = [
      {
        name    = "news-retrieval"
        # 30 days - matches company_news's retention window.
        command = ["python", "__main__.py", "expire-articles", "--domain", "vc_commentary", "--days", "30"]
      }
    ]
  })
}

resource "aws_cloudwatch_event_rule" "news_retrieval_adverse_media_expire_weekly" {
  name = "${var.env}-news-retrieval-adverse-media-expire-weekly"
  # Sunday 06:15 UTC - offset from vc_commentary's own 06:00 UTC expiry job
  # above, so neither cleanup job overlaps with the other.
  schedule_expression = "cron(15 6 ? * SUN *)"
}

resource "aws_cloudwatch_event_target" "news_retrieval_adverse_media_expire_weekly" {
  rule     = aws_cloudwatch_event_rule.news_retrieval_adverse_media_expire_weekly.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn

  ecs_target {
    # Family-only ARN (no revision suffix) - see comment on the daily fetch
    # target above for why this is unpinned rather than a specific revision.
    task_definition_arn = "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${aws_ecs_task_definition.news_retrieval.family}"
    launch_type         = "FARGATE"
    network_configuration {
      subnets          = var.public_subnet_ids
      security_groups  = [var.news_sg_id]
      assign_public_ip = true
    }
  }

  input = jsonencode({
    containerOverrides = [
      {
        name    = "news-retrieval"
        # 30 days - matches company_news's retention window.
        command = ["python", "__main__.py", "expire-articles", "--domain", "adverse_media", "--days", "30"]
      }
    ]
  })
}

resource "aws_cloudwatch_event_rule" "news_retrieval_ai_news_expire_weekly" {
  name = "${var.env}-news-retrieval-ai-news-expire-weekly"
  # Sunday 06:30 UTC - offset from adverse_media's own 06:15 UTC expiry job
  # above, so neither cleanup job overlaps with the other. ai_news has no
  # scheduled daily fetch job today (fetch is manual/CLI-only), so there is
  # no daily-job time to avoid colliding with here.
  schedule_expression = "cron(30 6 ? * SUN *)"
}

resource "aws_cloudwatch_event_target" "news_retrieval_ai_news_expire_weekly" {
  rule     = aws_cloudwatch_event_rule.news_retrieval_ai_news_expire_weekly.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn

  ecs_target {
    # Family-only ARN (no revision suffix) - see comment on the daily fetch
    # target above for why this is unpinned rather than a specific revision.
    task_definition_arn = "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${aws_ecs_task_definition.news_retrieval.family}"
    launch_type         = "FARGATE"
    network_configuration {
      subnets          = var.public_subnet_ids
      security_groups  = [var.news_sg_id]
      assign_public_ip = true
    }
  }

  input = jsonencode({
    containerOverrides = [
      {
        name    = "news-retrieval"
        # 30 days - matches company_news's retention window.
        command = ["python", "__main__.py", "expire-articles", "--domain", "ai_news", "--days", "30"]
      }
    ]
  })
}

resource "aws_cloudwatch_event_rule" "news_retrieval_smart_money_expire_weekly" {
  name = "${var.env}-news-retrieval-smart-money-expire-weekly"
  # Sunday 06:45 UTC - offset from ai_news's own 06:30 UTC expiry job above,
  # so neither cleanup job overlaps with the other. smart_money has no
  # scheduled daily fetch job today (fetch is manual/CLI-only), same as
  # ai_news above.
  schedule_expression = "cron(45 6 ? * SUN *)"
}

resource "aws_cloudwatch_event_target" "news_retrieval_smart_money_expire_weekly" {
  rule     = aws_cloudwatch_event_rule.news_retrieval_smart_money_expire_weekly.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn

  ecs_target {
    # Family-only ARN (no revision suffix) - see comment on the daily fetch
    # target above for why this is unpinned rather than a specific revision.
    task_definition_arn = "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${aws_ecs_task_definition.news_retrieval.family}"
    launch_type         = "FARGATE"
    network_configuration {
      subnets          = var.public_subnet_ids
      security_groups  = [var.news_sg_id]
      assign_public_ip = true
    }
  }

  input = jsonencode({
    containerOverrides = [
      {
        name    = "news-retrieval"
        # 30 days - matches company_news's retention window.
        command = ["python", "__main__.py", "expire-articles", "--domain", "smart_money", "--days", "30"]
      }
    ]
  })
}

resource "aws_cloudwatch_event_rule" "news_retrieval_vc_commentary_daily" {
  name                = "${var.env}-news-retrieval-vc-commentary-daily"
  schedule_expression = "cron(0 3 * * ? *)"
}

resource "aws_cloudwatch_event_target" "news_retrieval_vc_commentary_daily" {
  rule     = aws_cloudwatch_event_rule.news_retrieval_vc_commentary_daily.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn

  ecs_target {
    # Family-only ARN (no revision suffix) - see comment on the daily fetch
    # target above for why this is unpinned rather than a specific revision.
    task_definition_arn = "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${aws_ecs_task_definition.news_retrieval.family}"
    launch_type         = "FARGATE"
    network_configuration {
      subnets          = var.public_subnet_ids
      security_groups  = [var.news_sg_id]
      assign_public_ip = true
    }
  }

  input = jsonencode({
    containerOverrides = [
      {
        name    = "news-retrieval"
        command = ["python", "__main__.py", "trigger", "--domain", "vc_commentary", "--days-back", "1"]
      }
    ]
  })
}

resource "aws_cloudwatch_event_rule" "news_retrieval_adverse_media_daily" {
  name                = "${var.env}-news-retrieval-adverse-media-daily"
  schedule_expression = "cron(0 3 * * ? *)"
}

resource "aws_cloudwatch_event_target" "news_retrieval_adverse_media_daily" {
  rule     = aws_cloudwatch_event_rule.news_retrieval_adverse_media_daily.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn

  ecs_target {
    # Family-only ARN (no revision suffix) - see comment on the daily fetch
    # target above for why this is unpinned rather than a specific revision.
    task_definition_arn = "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${aws_ecs_task_definition.news_retrieval.family}"
    launch_type         = "FARGATE"
    network_configuration {
      subnets          = var.public_subnet_ids
      security_groups  = [var.news_sg_id]
      assign_public_ip = true
    }
  }

  input = jsonencode({
    containerOverrides = [
      {
        name    = "news-retrieval"
        command = ["python", "__main__.py", "trigger", "--domain", "adverse_media", "--days-back", "1"]
      }
    ]
  })
}

resource "aws_ecs_task_definition" "signal_detection" {
  family                   = "${var.env}-signal-detection"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024"
  memory                   = "2048"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn


  container_definitions = jsonencode([
    {
      name  = "signal-detection"
      image = "${var.ecr_registry}/ocn/signal-detection:${var.image_tag}"
      portMappings = [
        { containerPort = 8002 }
      ]
      environment = [
        { name = "POSTGRES_HOST",       value = var.rds_endpoint },
        { name = "POSTGRES_PORT",       value = "5432" },
        { name = "POSTGRES_DB",         value = "signal_detection_db" },
        { name = "POSTGRES_USER",       value = "signal_user" },
        { name = "PGSSLMODE",           value = "require" },
        { name = "AUTH_SERVICE_URL",    value = "http://auth-service.${var.env}.ocn.internal:8001" },
        { name = "NEWS_RETRIEVAL_URL",  value = "http://news-retrieval.${var.env}.ocn.internal:8000" },
        { name = "QDRANT_HOST",         value = var.qdrant_host },
        { name = "QDRANT_PORT",         value = "6333" },
        { name = "LANGFUSE_HOST",       value = "https://cloud.langfuse.com" }
      ]
      secrets = [
        {
          name      = "POSTGRES_PASSWORD"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/signal-detection:POSTGRES_PASSWORD::"
        },
        {
          name      = "OPENROUTER_API_KEY"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/signal-detection:OPENROUTER_API_KEY::"
        },
        {
          name      = "QDRANT_API_KEY"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/signal-detection:QDRANT_API_KEY::"
        },
        {
          name      = "LANGFUSE_SECRET_KEY"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/signal-detection:LANGFUSE_SECRET_KEY::"
        },
        {
          name      = "LANGFUSE_PUBLIC_KEY"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/signal-detection:LANGFUSE_PUBLIC_KEY::"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/${var.env}/signal-detection"
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])

  lifecycle {
    ignore_changes = [container_definitions]
  }
}


resource "aws_service_discovery_service" "signal_detection" {
  name = "signal-detection"
  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id
    dns_records {
      ttl  = 10
      type = "A"
    }
  }
}


resource "aws_ecs_service" "signal_detection" {
  name            = "${var.env}-signal-detection"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.signal_detection.arn
  desired_count   = 1
  launch_type     = "FARGATE"


  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.signal_sg_id]
    assign_public_ip = false
  }


  service_registries {
    registry_arn = aws_service_discovery_service.signal_detection.arn
  }

  lifecycle {
    ignore_changes = [task_definition]
  }
}

data "aws_secretsmanager_secret" "signal_detection_agent" {
  name = "ocn/${var.env}/signal-detection-agent"
}

resource "aws_ecs_task_definition" "signal_detection_agent" {
  family                   = "${var.env}-signal-detection-agent"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024"
  memory                   = "2048"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task_exec_ssm.arn

  container_definitions = jsonencode([
    {
      name  = "signal-detection-agent"
      image = "${var.ecr_registry}/ocn/signal-detection-agent:${var.image_tag}"
      portMappings = [
        { containerPort = 8003 }
      ]
      environment = [
        { name = "POSTGRES_HOST",          value = var.rds_endpoint },
        { name = "POSTGRES_PORT",          value = "5432" },
        { name = "POSTGRES_DB",            value = "signal_detection_db" },
        { name = "POSTGRES_USER",          value = "signal_user" },
        { name = "PGSSLMODE",              value = "require" },
        { name = "NEWS_RETRIEVAL_URL",     value = "http://news-retrieval.${var.env}.ocn.internal:8000" },
        { name = "RESEARCH_UNIVERSE_URL",  value = "http://research-universe.${var.env}.ocn.internal:8007" },
        { name = "OPENAI_BASE_URL",        value = "https://openrouter.ai/api/v1" },
        { name = "SIGNAL_DETECTION_MODEL",    value = "anthropic/claude-sonnet-4-6" },
        { name = "SIGNAL_DETECTION_MODEL_V2", value = "openai/gpt-4o-mini" },
        { name = "SEC_FILING_MODEL",          value = "openai/gpt-4.1" }
      ]
      secrets = [
        {
          name      = "POSTGRES_PASSWORD"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/signal-detection:POSTGRES_PASSWORD::"
        },
        {
          name      = "OPENAI_API_KEY"
          valueFrom = "${data.aws_secretsmanager_secret.signal_detection_agent.arn}:OPENAI_API_KEY::"
        },
        {
          name      = "RESEARCH_UNIVERSE_API_KEY"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/news-retrieval:RESEARCH_UNIVERSE_API_KEY::"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/${var.env}/signal-detection-agent"
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])

  lifecycle {
    ignore_changes = [container_definitions, task_role_arn]
  }
}


resource "aws_service_discovery_service" "signal_detection_agent" {
  name = "signal-detection-agent"
  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id
    dns_records {
      ttl  = 10
      type = "A"
    }
  }
}


# Daily SEC filing classification job. signal-detection-agent reads filing
# metadata (form_type, accession_number, primary_doc_url, item_codes, ...)
# and the tracked ticker list from news-retrieval's /market/* endpoints -
# it never calls SEC EDGAR's submissions API itself, only fetches each
# filing's body text directly (adapters/sec_edgar.py, text-fetch only).
# Scheduled for 13:00 UTC, one hour after news-retrieval's own sec_filings
# poller (12:00 UTC, see news-retrieval's CloudWatch rule) so this job always
# reads that day's freshly-fetched filings, not yesterday's. This runs AFTER
# signal-herald's unrelated 12:30 UTC digest run, so that day's filings won't
# appear in that day's digest. Note stage 2 (real classification) is
# currently commented out in filing_classifier.py, so this job only produces
# stage-1 narrative summaries for now.
resource "aws_cloudwatch_event_rule" "signal_detection_agent_filings_daily" {
  name                = "${var.env}-signal-detection-agent-filings-daily"
  description         = "Classify new SEC 8-K/10-Q/10-K filings (fetched by news-retrieval's poller) for the tracked ticker universe once daily"
  schedule_expression = "cron(0 13 * * ? *)"
  state               = "ENABLED"
}


resource "aws_cloudwatch_event_target" "signal_detection_agent_filings_daily" {
  rule     = aws_cloudwatch_event_rule.signal_detection_agent_filings_daily.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn
  ecs_target {
    # Family-only ARN (no revision suffix) - see comment on
    # news_retrieval_taiwan_market_signal's target above for why this is
    # unpinned rather than a specific revision.
    task_definition_arn = "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${aws_ecs_task_definition.signal_detection_agent.family}"
    launch_type         = "FARGATE"
    network_configuration {
      subnets         = var.private_subnet_ids
      security_groups = [var.signal_detection_agent_sg_id]
    }
  }
  input = jsonencode({
    containerOverrides = [
      {
        name    = "signal-detection-agent"
        command = ["python", "-m", "src", "classify-filings"]
      }
    ]
  })
}


resource "aws_cloudwatch_event_rule" "signal_detection_agent_taiwan_signals" {
  name        = "${var.env}-signal-detection-agent-taiwan-signals"
  description = "Classify today's pooled taiwan_market_signal news-retrieval runs (rank/clause-lookup/translate/GDELT-classify), twice daily: post-Asia-close and pre-US-open"
  # 14:00 UTC = right after news-retrieval's last Taiwan fetch of the
  # window (01:00-16:00 UTC, see news_retrieval_taiwan_market_signal above)
  # has had time to land the evening 重大訊息 announcement cluster -
  # "post-Asia-close" pass.
  # 21:00 UTC = well before the next US trading day's pre-market (13:00 UTC
  # / 9am ET open) - "pre-US-open" pass, catching anything the 14:00 UTC
  # run missed plus same-day re-polls.
  # Both passes call classify-taiwan-signals with default from_date=to_date
  # =today (UTC), which pools ALL of today's completed runs so far (not
  # just the latest) and skips already-classified source_ids, so the two
  # runs are additive rather than duplicating work.
  schedule_expression = "cron(0 14,21 ? * MON-FRI *)"
}

resource "aws_cloudwatch_event_target" "signal_detection_agent_taiwan_signals" {
  rule     = aws_cloudwatch_event_rule.signal_detection_agent_taiwan_signals.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn
  ecs_target {
    # Family-only ARN (no revision suffix) - see comment on
    # news_retrieval_taiwan_market_signal's target above for why this is
    # unpinned rather than a specific revision.
    task_definition_arn = "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${aws_ecs_task_definition.signal_detection_agent.family}"
    launch_type         = "FARGATE"
    network_configuration {
      subnets         = var.private_subnet_ids
      security_groups = [var.signal_detection_agent_sg_id]
    }
  }
  input = jsonencode({
    containerOverrides = [
      {
        name    = "signal-detection-agent"
        command = ["python", "-m", "src", "classify-taiwan-signals"]
      }
    ]
  })
}

resource "aws_cloudwatch_event_rule" "signal_detection_agent_korea_signals" {
  name        = "${var.env}-signal-detection-agent-korea-signals"
  description = "Classify today's pooled korea_market_signal news-retrieval runs (S2-S7 arithmetic/lookup + S7 model call + translate), twice daily"
  # news-retrieval fetches korea_market_signal every 4 hours, unbounded
  # across all 24h/7 days (00/04/08/12/16/20 UTC - see
  # news_retrieval_korea_market_signal above), unlike Taiwan's
  # trading-hours-bound schedule - so this rule's own timing isn't picking
  # a "market close" moment the way Taiwan's is, just spacing two passes
  # far enough apart to each pool a meaningful number of fetch cycles.
  #
  # Corrected 2026-09-23: an earlier version of this schedule (15:00/22:00
  # UTC) was designed by reasoning about UTC-relative-to-Taiwan's-own-
  # framing ("post-Asia-close, pre-US-open") without actually converting
  # to real KST (UTC+9) - converting it after the fact showed those two
  # times land at 00:00 and 07:00 KST, the middle of the Korean night and
  # early pre-dawn, not "after KST business hours close" as that version's
  # own comment incorrectly claimed. Recomputed properly below.
  #
  # 13:00 UTC = 22:00 KST (right after Korea's evening filing window - the
  # spec's own "filings lodged in the evening, Korea time" - and right
  # after the 12:00 UTC fetch has landed, pooling 00/04/08/12 UTC) AND
  # 09:00 ET / 13:30 UTC summary = right at US market open (9:30am ET) -
  # a trader has the digest before the US trading day starts.
  # 21:00 UTC = 06:00 KST (right after the 20:00 UTC fetch, catching
  # Korea's very early morning filings before that day's Korean business
  # hours even start) AND 17:00 ET / 21:30 UTC summary = end of the US
  # trading day - a second checkpoint before the desk closes out.
  # Both passes call classify-korea-signals with default from_date=to_date=
  # today (UTC), which pools ALL of today's completed runs so far (not just
  # the latest) and skips already-classified source_ids (via the
  # idx_agent_classifications_korea_source_id unique index - see db.py), so
  # the two runs are additive rather than duplicating work, same pattern as
  # Taiwan's own two-pass schedule.
  schedule_expression = "cron(0 13,21 * * ? *)"
  # Paused 2026-09-23 (explicit request) - see
  # news_retrieval_korea_market_signal's own comment on why this is set
  # here rather than left as a CLI-only disable-rule call.
  state = "DISABLED"
}

resource "aws_cloudwatch_event_target" "signal_detection_agent_korea_signals" {
  rule     = aws_cloudwatch_event_rule.signal_detection_agent_korea_signals.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn
  ecs_target {
    # Family-only ARN (no revision suffix) - same reasoning as Taiwan's own
    # target above.
    task_definition_arn = "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${aws_ecs_task_definition.signal_detection_agent.family}"
    launch_type         = "FARGATE"
    network_configuration {
      subnets         = var.private_subnet_ids
      security_groups = [var.signal_detection_agent_sg_id]
    }
  }
  input = jsonencode({
    containerOverrides = [
      {
        name    = "signal-detection-agent"
        command = ["python", "-m", "src", "classify-korea-signals"]
      }
    ]
  })
}

resource "aws_cloudwatch_event_rule" "signal_detection_agent_korea_signals_summary" {
  name        = "${var.env}-signal-detection-agent-korea-signals-summary"
  description = "Generate the spec Section 8.4 twice-daily trader summary from today's already-classified korea_market_signal rows"
  # 30 minutes after each classify-korea-signals pass (13:00/21:00 UTC
  # above), not at the same time - classification itself takes real time
  # (S7's own per-article model call, plus translation, over however many
  # articles pooled that run), so summarizing at the exact same timestamp
  # risks reading a DB that classification hasn't finished writing to
  # yet. 30 minutes is a deliberate buffer, not a measured worst-case
  # runtime - revisit if a real run is ever confirmed to still be
  # in-flight past this offset.
  # 13:30 UTC = 9:30am ET, right at US market open - the trader has the
  # digest before the trading day starts. 21:30 UTC = 5:30pm ET, just
  # after the US trading day ends - a second checkpoint before close-out.
  # summarize-korea-signals only reads agent_classifications (no
  # news-retrieval fetch, no LLM classification calls of its own beyond
  # the one summary-writer call) - so this is a fast job regardless of
  # how large the classify pass was.
  schedule_expression = "cron(30 13,21 * * ? *)"
  # Paused 2026-09-23 (explicit request) - see
  # news_retrieval_korea_market_signal's own comment on why this is set
  # here rather than left as a CLI-only disable-rule call.
  state = "DISABLED"
}

resource "aws_cloudwatch_event_target" "signal_detection_agent_korea_signals_summary" {
  rule     = aws_cloudwatch_event_rule.signal_detection_agent_korea_signals_summary.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn
  ecs_target {
    task_definition_arn = "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${aws_ecs_task_definition.signal_detection_agent.family}"
    launch_type         = "FARGATE"
    network_configuration {
      subnets         = var.private_subnet_ids
      security_groups = [var.signal_detection_agent_sg_id]
    }
  }
  input = jsonencode({
    containerOverrides = [
      {
        name    = "signal-detection-agent"
        command = ["python", "-m", "src", "summarize-korea-signals"]
      }
    ]
  })
}

# Weekly classification retention for the domain signal-detection-agent
# actually consumes this way (ai_news -> source_type='news'). sec_filing and
# taiwan_market_signal are intentionally excluded - neither has a
# source-side expiry in news-retrieval today. Runs 1 hour after its
# corresponding news_retrieval_*_expire_weekly rule, so classifications are
# only ever expired after their source article has already been deleted,
# never the other way around. Deliberately kept longer than its
# news-retrieval source's own article retention - news: 180 days here vs 30
# days for ai_news - a classification is allowed to outlive its source
# article.
resource "aws_cloudwatch_event_rule" "signal_detection_agent_news_expire_weekly" {
  name                = "${var.env}-signal-detection-agent-news-expire-weekly"
  description         = "Delete news classifications older than 180 days (longer than news-retrieval's 30-day ai_news article retention, by design)"
  schedule_expression = "cron(30 7 ? * SUN *)"
}

resource "aws_cloudwatch_event_target" "signal_detection_agent_news_expire_weekly" {
  rule     = aws_cloudwatch_event_rule.signal_detection_agent_news_expire_weekly.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn
  ecs_target {
    task_definition_arn = "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${aws_ecs_task_definition.signal_detection_agent.family}"
    launch_type         = "FARGATE"
    network_configuration {
      subnets         = var.private_subnet_ids
      security_groups = [var.signal_detection_agent_sg_id]
    }
  }
  input = jsonencode({
    containerOverrides = [
      {
        name    = "signal-detection-agent"
        command = ["python", "-m", "src", "expire-classifications", "--source-type", "news", "--days", "180"]
      }
    ]
  })
}

# geopolitical_signal funnel: Stage A (rule-based) -> Stage B (talk vs
# action LLM call) -> Stage C (company/category tagging, reads the
# geopolitical_signal_companies cache). Stages A/B/C are NOT independent
# jobs - B only acts on rows A just wrote ('waiting'), and C only acts on
# rows B just wrote ('signal'/HIGH) - so they run as one CLI command
# (run-geopolitical-signal-pipeline) inside a single scheduled task rather
# than three separately-scheduled triggers. Three separate cron rules
# risked B or C firing before the prior stage's run had actually finished
# (e.g. Stage A running long on a heavy news day); a single sequential
# command removes that race entirely.
#   03:00 - company/category cache refresh (research-universe -> cache
#            table). Kept on its own schedule, independent of the news
#            cycle - company/ticker/category data changes rarely, so it
#            doesn't need to run every time the pipeline does. Runs
#            before the 05:00 UTC pipeline slot so Stage C's cache read
#            is never more than ~2 hours stale, and before a first-ever
#            deploy's first pipeline run so the cache starts populated.
#   05:00 - Stage A -> Stage B -> Stage C -> Stage D, in sequence, in one
#            task. This is a FALLBACK, not the primary trigger: the
#            primary path is news-retrieval's own --callback-url webhook
#            (news_retrieval_geopolitical_news_daily above passes
#            /webhooks/news-retrieval-run-completed as its callback),
#            which kicks off this same pipeline in signal-detection-
#            agent's running server process the moment that day's fetch
#            actually completes - correct regardless of how long the
#            fetch takes, unlike a fixed offset from news-retrieval's own
#            02:00 UTC schedule. This 05:00 UTC rule stays as a safety
#            net for if that webhook delivery is ever lost (it's
#            fire-and-forget on news-retrieval's side - no retry, see
#            _fire_webhook in news-retrieval/src/controllers/run.py) -
#            running the pipeline twice in one day is harmless, since
#            every stage's worklist query only selects rows the previous
#            stage hasn't processed yet.
resource "aws_cloudwatch_event_rule" "signal_detection_agent_geopolitical_signal_cache_refresh_daily" {
  name                = "${var.env}-signal-detection-agent-geo-signal-cache-refresh-daily"
  description         = "Refresh geopolitical_signal_companies cache (ticker/name/category) from research-universe"
  schedule_expression = "cron(0 3 * * ? *)"
  state               = "ENABLED"
}

resource "aws_cloudwatch_event_target" "signal_detection_agent_geopolitical_signal_cache_refresh_daily" {
  rule     = aws_cloudwatch_event_rule.signal_detection_agent_geopolitical_signal_cache_refresh_daily.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn
  ecs_target {
    task_definition_arn = "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${aws_ecs_task_definition.signal_detection_agent.family}"
    launch_type         = "FARGATE"
    network_configuration {
      subnets         = var.private_subnet_ids
      security_groups = [var.signal_detection_agent_sg_id]
    }
  }
  input = jsonencode({
    containerOverrides = [
      {
        name    = "signal-detection-agent"
        command = ["python", "-m", "src", "refresh-geopolitical-category-map"]
      }
    ]
  })
}

resource "aws_cloudwatch_event_rule" "signal_detection_agent_geopolitical_signal_pipeline_daily" {
  name                = "${var.env}-signal-detection-agent-geo-signal-pipeline-daily"
  description         = "geopolitical_signal Stage A -> Stage B -> Stage C, run sequentially in one task"
  schedule_expression = "cron(0 5 * * ? *)"
  state               = "ENABLED"
}

resource "aws_cloudwatch_event_target" "signal_detection_agent_geopolitical_signal_pipeline_daily" {
  rule     = aws_cloudwatch_event_rule.signal_detection_agent_geopolitical_signal_pipeline_daily.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn
  ecs_target {
    task_definition_arn = "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${aws_ecs_task_definition.signal_detection_agent.family}"
    launch_type         = "FARGATE"
    network_configuration {
      subnets         = var.private_subnet_ids
      security_groups = [var.signal_detection_agent_sg_id]
    }
  }
  input = jsonencode({
    containerOverrides = [
      {
        name    = "signal-detection-agent"
        command = ["python", "-m", "src", "run-geopolitical-signal-pipeline"]
      }
    ]
  })
}


resource "aws_ecs_service" "signal_detection_agent" {
  name            = "${var.env}-signal-detection-agent"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.signal_detection_agent.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.signal_detection_agent_sg_id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.signal_detection_agent.arn
  }

  lifecycle {
    ignore_changes = [task_definition]
  }
}



resource "aws_iam_role" "ecs_events" {
  name = "${var.env}-ecs-events-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}


resource "aws_iam_role_policy" "ecs_events_run_task" {
  name = "${var.env}-ecs-events-run-task"
  role = aws_iam_role.ecs_events.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["ecs:RunTask"]
        Resource = [
          "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/staging-signal-detection:*",
          "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/staging-signal-herald:*",
          "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/staging-research-universe:*",
          "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/staging-news-retrieval:*",
          "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/staging-signal-detection-agent:*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [
          aws_iam_role.ecs_task_execution.arn,
          aws_iam_role.ecs_task_exec_ssm.arn,
        ]
      }
    ]
  })
}




resource "aws_ecs_task_definition" "api_gateway" {
  family                   = "${var.env}-api-gateway"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn


  container_definitions = jsonencode([
    {
      name  = "api-gateway"
      image = "${var.ecr_registry}/ocn/api-gateway:${var.image_tag}"
      portMappings = [
        { containerPort = 8004 }
      ]
      environment = [
        { name = "GATEWAY_AUTH_URL",         value = "http://auth-service.${var.env}.ocn.internal:8001" },
        { name = "GATEWAY_NEWS_URL",         value = "http://news-retrieval.${var.env}.ocn.internal:8000" },
        { name = "GATEWAY_SIGNAL_URL",       value = "http://signal-detection.${var.env}.ocn.internal:8002" },
        { name = "GATEWAY_SIGNAL_AGENT_URL", value = "http://signal-detection-agent.${var.env}.ocn.internal:8003" },
        { name = "GATEWAY_CORS_ORIGINS",     value = var.gateway_cors_origins }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/${var.env}/api-gateway"
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])

  lifecycle {
    ignore_changes = [container_definitions]
  }
}


resource "aws_service_discovery_service" "api_gateway" {
  name = "api-gateway"
  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id
    dns_records {
      ttl  = 10
      type = "A"
    }
  }
}


resource "aws_ecs_service" "api_gateway" {
  name            = "${var.env}-api-gateway"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api_gateway.arn
  desired_count   = 1
  launch_type     = "FARGATE"


  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.gateway_sg_id]
    assign_public_ip = false
  }


  load_balancer {
    target_group_arn = var.api_gateway_tg_arn
    container_name   = "api-gateway"
    container_port   = 8004
  }


  service_registries {
    registry_arn = aws_service_discovery_service.api_gateway.arn
  }

  lifecycle {
    ignore_changes = [task_definition]
  }
}


data "aws_secretsmanager_secret" "lucky_clarke" {
  name = "ocn/${var.env}/lucky-clarke"
}

resource "aws_ecs_task_definition" "lucky_clarke" {
  family                   = "${var.env}-lucky-clarke"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn


  container_definitions = jsonencode([
    {
      name  = "lucky-clarke"
      image = "${var.ecr_registry}/ocn/lucky-clarke:${var.image_tag}"
      portMappings = [
        { containerPort = 8005 }
      ]
      environment = [
        { name = "SIGNAL_DETECTION_URL",  value = "http://signal-detection.${var.env}.ocn.internal:8002" },
        { name = "LUCKY_CLARKE_URL",      value = "http://lucky-clarke.${var.env}.ocn.internal:8005" },
        { name = "SIGNAL_CALLER_SUB",     value = "1" },
        { name = "OPENROUTER_MODEL",      value = "openai/gpt-4o-mini" },
        { name = "AWS_REGION",            value = var.aws_region },
      ]
      secrets = [
        {
          name      = "OPENROUTER_API_KEY"
          valueFrom = "${data.aws_secretsmanager_secret.lucky_clarke.arn}:OPENROUTER_API_KEY::"
        },
        {
          name      = "SMTP_HOST"
          valueFrom = "${data.aws_secretsmanager_secret.lucky_clarke.arn}:SMTP_HOST::"
        },
        {
          name      = "SMTP_USER"
          valueFrom = "${data.aws_secretsmanager_secret.lucky_clarke.arn}:SMTP_USER::"
        },
        {
          name      = "SMTP_PASSWORD"
          valueFrom = "${data.aws_secretsmanager_secret.lucky_clarke.arn}:SMTP_PASSWORD::"
        },
        {
          name      = "SMTP_FROM"
          valueFrom = "${data.aws_secretsmanager_secret.lucky_clarke.arn}:SMTP_FROM::"
        },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/${var.env}/lucky-clarke"
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])

  lifecycle {
    ignore_changes = [container_definitions]
  }
}


resource "aws_service_discovery_service" "lucky_clarke" {
  name = "lucky-clarke"
  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id
    dns_records {
      ttl  = 10
      type = "A"
    }
  }
}


resource "aws_ecs_service" "lucky_clarke" {
  name            = "${var.env}-lucky-clarke"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.lucky_clarke.arn
  desired_count   = 1
  launch_type     = "FARGATE"


  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.lucky_clarke_sg_id]
    assign_public_ip = false
  }


  service_registries {
    registry_arn = aws_service_discovery_service.lucky_clarke.arn
  }

  lifecycle {
    ignore_changes = [task_definition]
  }
}




data "aws_secretsmanager_secret" "signal_herald" {
  name = "ocn/${var.env}/signal-herald"
}

resource "aws_ecs_task_definition" "signal_herald" {
  family                   = "${var.env}-signal-herald"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn

  container_definitions = jsonencode([
    {
      name  = "signal-herald"
      image = "${var.ecr_registry}/ocn/signal-herald:${var.image_tag}"
      portMappings = [
        { containerPort = 8006 }
      ]
      environment = [
        { name = "SIGNAL_AGENT_URL",   value = "http://signal-detection-agent.${var.env}.ocn.internal:8003" },
        { name = "SIGNAL_HERALD_URL",  value = "http://signal-herald.${var.env}.ocn.internal:8006" },
        { name = "SIGNAL_CALLER_SUB",  value = "1" },
        { name = "OPENROUTER_MODEL",   value = "openai/gpt-4o-mini" },
      ]
      secrets = [
        {
          name      = "OPENROUTER_API_KEY"
          valueFrom = "${data.aws_secretsmanager_secret.signal_herald.arn}:OPENROUTER_API_KEY::"
        },
        {
          name      = "SMTP_HOST"
          valueFrom = "${data.aws_secretsmanager_secret.signal_herald.arn}:SMTP_HOST::"
        },
        {
          name      = "SMTP_USER"
          valueFrom = "${data.aws_secretsmanager_secret.signal_herald.arn}:SMTP_USER::"
        },
        {
          name      = "SMTP_PASSWORD"
          valueFrom = "${data.aws_secretsmanager_secret.signal_herald.arn}:SMTP_PASSWORD::"
        },
        {
          name      = "SMTP_FROM"
          valueFrom = "${data.aws_secretsmanager_secret.signal_herald.arn}:SMTP_FROM::"
        },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/${var.env}/signal-herald"
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])

  lifecycle {
    ignore_changes = [container_definitions]
  }
}


resource "aws_service_discovery_service" "signal_herald" {
  name = "signal-herald"
  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id
    dns_records {
      ttl  = 10
      type = "A"
    }
  }
}


resource "aws_ecs_service" "signal_herald" {
  name            = "${var.env}-signal-herald"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.signal_herald.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.signal_herald_sg_id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.signal_herald.arn
  }

  lifecycle {
    ignore_changes = [task_definition]
  }
}


resource "aws_cloudwatch_event_rule" "signal_herald_daily" {
  name                = "${var.env}-signal-herald-daily"
  schedule_expression = "cron(30 12 ? * MON-FRI *)"
}


resource "aws_cloudwatch_event_target" "signal_herald_daily" {
  rule     = aws_cloudwatch_event_rule.signal_herald_daily.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn
  ecs_target {
    # Family-only ARN (no revision suffix) - see comment on
    # news_retrieval_taiwan_market_signal's target above for why this is
    # unpinned rather than a specific revision (CI/CD registers new task-def
    # revisions directly, bypassing terraform apply, so a pinned ARN here
    # drifts stale the moment CI/CD deploys next).
    task_definition_arn = "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${aws_ecs_task_definition.signal_herald.family}"
    launch_type         = "FARGATE"
    network_configuration {
      subnets         = var.private_subnet_ids
      security_groups = [var.signal_herald_sg_id]
    }
  }
  input = jsonencode({
    containerOverrides = [
      {
        name    = "signal-herald"
        command = ["python", "-m", "src", "run", "--force"]
      }
    ]
  })
}




# ---------------------------------------------------------------------------
# research-universe (port 8007)
# ---------------------------------------------------------------------------

data "aws_secretsmanager_secret" "research_universe" {
  name = "ocn/${var.env}/research-universe"
}

resource "aws_ecs_task_definition" "research_universe" {
  family                   = "${var.env}-research-universe"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task_exec_ssm.arn

  container_definitions = jsonencode([
    {
      name  = "research-universe"
      image = "${var.ecr_registry}/ocn/research-universe:${var.image_tag}"
      portMappings = [
        { containerPort = 8007 }
      ]
      environment = [
        { name = "POSTGRES_HOST",      value = var.rds_endpoint },
        { name = "POSTGRES_PORT",      value = "5432" },
        { name = "POSTGRES_DB",        value = "research_universe_db" },
        { name = "POSTGRES_USER",      value = "research_universe_user" },
        { name = "PGSSLMODE",          value = "require" },
        { name = "OPENROUTER_MODEL",   value = "anthropic/claude-sonnet-4-6" },
        { name = "API_PREFIX",         value = "/universe" },
      ]
      secrets = [
        {
          name      = "POSTGRES_PASSWORD"
          valueFrom = "${data.aws_secretsmanager_secret.research_universe.arn}:POSTGRES_PASSWORD::"
        },
        {
          name      = "OPENROUTER_API_KEY"
          valueFrom = "${data.aws_secretsmanager_secret.research_universe.arn}:OPENROUTER_API_KEY::"
        },
        {
          name      = "CORS_ORIGINS"
          valueFrom = "${data.aws_secretsmanager_secret.research_universe.arn}:CORS_ORIGINS::"
        },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/${var.env}/research-universe"
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])

  lifecycle {
    ignore_changes = [container_definitions]
  }
}


resource "aws_service_discovery_service" "research_universe" {
  name = "research-universe"
  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id
    dns_records {
      ttl  = 10
      type = "A"
    }
  }
}


resource "aws_ecs_service" "research_universe" {
  name                   = "${var.env}-research-universe"
  cluster                = aws_ecs_cluster.main.id
  task_definition        = aws_ecs_task_definition.research_universe.arn
  desired_count          = 1
  launch_type            = "FARGATE"
  enable_execute_command = true

  load_balancer {
    target_group_arn = var.research_universe_tg_arn
    container_name   = "research-universe"
    container_port   = 8007
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.research_universe_sg_id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.research_universe.arn
  }

  lifecycle {
    ignore_changes = [task_definition]
  }
}


resource "aws_cloudwatch_event_rule" "research_universe_scan" {
  name                = "${var.env}-research-universe-scan"
  description         = "Universe enrichment: full 19-category scan every 15 days"
  schedule_expression = "rate(15 days)"  # every 15 days at 09:00 UTC
}


resource "aws_cloudwatch_event_target" "research_universe_scan" {
  rule     = aws_cloudwatch_event_rule.research_universe_scan.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn

  ecs_target {
    # Family-only ARN (no revision suffix) - see comment on
    # news_retrieval_taiwan_market_signal's target above for why this is
    # unpinned rather than a specific revision.
    task_definition_arn = "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${aws_ecs_task_definition.research_universe.family}"
    launch_type         = "FARGATE"
    network_configuration {
      subnets         = var.private_subnet_ids
      security_groups = [var.research_universe_sg_id]
    }
  }

  input = jsonencode({
    containerOverrides = [
      {
        name    = "research-universe"
        command = ["python", "-m", "src", "scan-all"]
      }
    ]
  })
}
