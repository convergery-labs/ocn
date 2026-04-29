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
        { name = "AUTH_SERVICE_URL", value = "http://auth-service.${var.env}.ocn.internal:8001" },
        { name = "OPENROUTER_MODEL", value = "openrouter/elephant-alpha" }
      ]
      secrets = [
        {
          name      = "POSTGRES_PASSWORD"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/news-retrieval:POSTGRES_PASSWORD::"
        },
        {
          name      = "OPENROUTER_API_KEY"
          valueFrom = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:ocn/${var.env}/news-retrieval:OPENROUTER_API_KEY::"
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

resource "aws_cloudwatch_event_rule" "promote_corpus" {
  name                = "${var.env}-promote-corpus-nightly"
  schedule_expression = "cron(0 0 * * ? *)"
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
        Effect   = "Allow"
        Action   = ["ecs:RunTask"]
        Resource = [aws_ecs_task_definition.signal_detection.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [aws_iam_role.ecs_task_execution.arn]
      }
    ]
  })
}


resource "aws_cloudwatch_event_target" "promote_corpus" {
  rule     = aws_cloudwatch_event_rule.promote_corpus.name
  arn      = aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.ecs_events.arn
  ecs_target {
    task_definition_arn = aws_ecs_task_definition.signal_detection.arn
    launch_type         = "FARGATE"
    network_configuration {
      subnets         = var.private_subnet_ids
      security_groups = [var.signal_sg_id]
    }
  }
  input = jsonencode({
    containerOverrides = [
      {
        name    = "signal-detection"
        command = ["python", "-m", "src", "promote-corpus"]
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
        { name = "GATEWAY_AUTH_URL",    value = "http://auth-service.${var.env}.ocn.internal:8001" },
        { name = "GATEWAY_NEWS_URL",    value = "http://news-retrieval.${var.env}.ocn.internal:8000" },
        { name = "GATEWAY_SIGNAL_URL",  value = "http://signal-detection.${var.env}.ocn.internal:8002" }
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
    subnets          = var.public_subnet_ids
    security_groups  = [var.gateway_sg_id]
    assign_public_ip = true
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
