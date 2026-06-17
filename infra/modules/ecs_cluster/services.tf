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
        { name = "AUTH_POSTGRES_HOST", value = var.rds_endpoint },
        { name = "AUTH_POSTGRES_PORT", value = "5432" },
        { name = "AUTH_POSTGRES_DB",   value = "auth_db" },
        { name = "AUTH_POSTGRES_USER", value = "auth_user" },
        { name = "PGSSLMODE",          value = "require" }
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
}

resource "aws_ecs_task_definition" "news_retrieval" {
  family                   = "${var.env}-news-retrieval"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn


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
        { name = "RESEARCH_UNIVERSE_URL",   value = "http://research-universe.${var.env}.ocn.internal:8007" },
        { name = "OPENROUTER_MODEL",        value = "openrouter/elephant-alpha" }
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
  name            = "${var.env}-news-retrieval"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.news_retrieval.arn
  desired_count   = 1
  launch_type     = "FARGATE"


  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.news_sg_id]
    assign_public_ip = false
  }


  service_registries {
    registry_arn = aws_service_discovery_service.news_retrieval.arn
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
    task_definition_arn = aws_ecs_task_definition.news_retrieval.arn
    launch_type         = "FARGATE"
    network_configuration {
      subnets         = var.private_subnet_ids
      security_groups = [var.news_sg_id]
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
        { name = "OPENAI_BASE_URL",        value = "https://openrouter.ai/api/v1" },
        { name = "SIGNAL_DETECTION_MODEL", value = "anthropic/claude-sonnet-4-6" }
      ]
      secrets = [
        {
          name      = "POSTGRES_PASSWORD"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/signal-detection:POSTGRES_PASSWORD::"
        },
        {
          name      = "OPENAI_API_KEY"
          valueFrom = "${data.aws_secretsmanager_secret.signal_detection_agent.arn}:OPENAI_API_KEY::"
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
          aws_ecs_task_definition.signal_detection.arn,
          aws_ecs_task_definition.signal_herald.arn,
          aws_ecs_task_definition.research_universe.arn,
          aws_ecs_task_definition.news_retrieval.arn,
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [aws_iam_role.ecs_task_execution.arn]
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
}


resource "aws_cloudwatch_event_rule" "signal_herald_daily" {
  name                = "${var.env}-signal-herald-daily"
  schedule_expression = "cron(0 14 ? * MON,THU *)"
}


resource "aws_cloudwatch_event_target" "signal_herald_daily" {
  rule     = aws_cloudwatch_event_rule.signal_herald_daily.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn
  ecs_target {
    task_definition_arn = aws_ecs_task_definition.signal_herald.arn
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
  name            = "${var.env}-research-universe"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.research_universe.arn
  desired_count   = 1
  launch_type     = "FARGATE"

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
    task_definition_arn = aws_ecs_task_definition.research_universe.arn
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
