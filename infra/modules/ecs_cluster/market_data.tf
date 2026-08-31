# ---------------------------------------------------------------------------
# Market data — DynamoDB tables, IAM, and CloudWatch scheduled pollers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# DynamoDB tables
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "market_quote" {
  name         = "ocn-market-quote"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "ticker"
  range_key    = "recorded_at"

  attribute {
    name = "ticker"
    type = "S"
  }
  attribute {
    name = "recorded_at"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = { env = var.env }
}

resource "aws_dynamodb_table" "market_indices" {
  name         = "ocn-market-indices"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "ticker"
  range_key    = "recorded_at"

  attribute {
    name = "ticker"
    type = "S"
  }
  attribute {
    name = "recorded_at"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = { env = var.env }
}

resource "aws_dynamodb_table" "market_status" {
  name         = "ocn-market-status"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "market"
  range_key    = "recorded_at"

  attribute {
    name = "market"
    type = "S"
  }
  attribute {
    name = "recorded_at"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = { env = var.env }
}

resource "aws_dynamodb_table" "market_overview" {
  name         = "ocn-market-overview"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "ticker"
  range_key    = "recorded_at"

  attribute {
    name = "ticker"
    type = "S"
  }
  attribute {
    name = "recorded_at"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = { env = var.env }
}

resource "aws_dynamodb_table" "market_price_history" {
  name         = "ocn-market-price-history"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "ticker"
  range_key    = "date"

  attribute {
    name = "ticker"
    type = "S"
  }
  attribute {
    name = "date"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = { env = var.env }
}

resource "aws_dynamodb_table" "market_earnings" {
  name         = "ocn-market-earnings"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "ticker"
  range_key    = "recorded_at"

  attribute {
    name = "ticker"
    type = "S"
  }
  attribute {
    name = "recorded_at"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = { env = var.env }
}


resource "aws_dynamodb_table" "sec_filings" {
  name         = "ocn-sec-filings"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "ticker"
  range_key    = "accession_number"

  attribute {
    name = "ticker"
    type = "S"
  }
  attribute {
    name = "accession_number"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = { env = var.env }
}

resource "aws_dynamodb_table" "market_macro" {
  name         = "ocn-market-macro"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "indicator"
  range_key    = "recorded_at"

  attribute {
    name = "indicator"
    type = "S"
  }
  attribute {
    name = "recorded_at"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = { env = var.env }
}

resource "aws_dynamodb_table" "market_lock" {
  name         = "ocn-market-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "lock_key"

  attribute {
    name = "lock_key"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = { env = var.env }
}


# ---------------------------------------------------------------------------
# IAM — allow news-retrieval ECS task role to read/write all market tables
# ---------------------------------------------------------------------------

resource "aws_iam_role_policy" "news_retrieval_dynamodb_market" {
  name = "${var.env}-news-retrieval-dynamodb-market"
  role = aws_iam_role.ecs_task_exec_ssm.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:BatchWriteItem",
          "dynamodb:Query",
          "dynamodb:GetItem",
          "dynamodb:DeleteItem",
        ]
        Resource = [
          aws_dynamodb_table.market_quote.arn,
          aws_dynamodb_table.market_indices.arn,
          aws_dynamodb_table.market_status.arn,
          aws_dynamodb_table.market_overview.arn,
          aws_dynamodb_table.market_price_history.arn,
          aws_dynamodb_table.market_earnings.arn,
          aws_dynamodb_table.market_lock.arn,
          aws_dynamodb_table.sec_filings.arn,
          aws_dynamodb_table.market_macro.arn,
        ]
      }
    ]
  })
}


# ---------------------------------------------------------------------------
# CloudWatch scheduled rules — poller
# ---------------------------------------------------------------------------

# Quotes mode: every 60 min during US market hours (Mon-Fri, 14:00-21:00 UTC)
resource "aws_cloudwatch_event_rule" "market_poll_quotes" {
  name                = "${var.env}-market-poll-quotes"
  description         = "Poll AV GLOBAL_QUOTE + MARKET_STATUS every 60 min during market hours → DynamoDB"
  schedule_expression = "cron(0 14-20 ? * MON-FRI *)"
}

resource "aws_cloudwatch_event_target" "market_poll_quotes" {
  rule     = aws_cloudwatch_event_rule.market_poll_quotes.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn

  ecs_target {
    task_definition_arn = replace(aws_ecs_task_definition.news_retrieval.arn, "/:\\d+$/", "")
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
        command = ["python", "__main__.py", "poll-market", "--mode", "quotes"]
      }
    ]
  })
}


# Daily mode: once at 00:30 UTC (overview, earnings, price history)
resource "aws_cloudwatch_event_rule" "market_poll_daily" {
  name                = "${var.env}-market-poll-daily"
  description         = "Poll AV OVERVIEW + EARNINGS + TIME_SERIES_DAILY_ADJUSTED once daily → DynamoDB"
  schedule_expression = "cron(30 0 * * ? *)"
}

resource "aws_cloudwatch_event_target" "market_poll_daily" {
  rule     = aws_cloudwatch_event_rule.market_poll_daily.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn

  ecs_target {
    task_definition_arn = replace(aws_ecs_task_definition.news_retrieval.arn, "/:\\d+$/", "")
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
        command = ["python", "__main__.py", "poll-market", "--mode", "daily"]
      }
    ]
  })
}


# SEC filings mode: once at 12:00 UTC (8-K/10-Q/10-K metadata + link)
resource "aws_cloudwatch_event_rule" "market_poll_sec_filings" {
  name                = "${var.env}-market-poll-sec-filings"
  description         = "Poll SEC EDGAR for new 8-K/10-Q/10-K filings once daily → DynamoDB"
  schedule_expression = "cron(0 12 * * ? *)"
}

resource "aws_cloudwatch_event_target" "market_poll_sec_filings" {
  rule     = aws_cloudwatch_event_rule.market_poll_sec_filings.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn

  ecs_target {
    task_definition_arn = replace(aws_ecs_task_definition.news_retrieval.arn, "/:\\d+$/", "")
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
        command = ["python", "__main__.py", "poll-market", "--mode", "sec_filings"]
      }
    ]
  })
}
