# infra

Part of the [ocn monorepo](../CLAUDE.md).

## Overview

Terraform infrastructure for the OCN platform. Provisions all AWS resources — VPC, RDS, ECS Fargate cluster, ALB, security groups, IAM roles, and CloudWatch logs — across environments. Remote state is stored in S3 with DynamoDB locking.

## Jira Board
| Board | URL | Project Key |
|-------|-----|-------------|
| OCN Board | https://opengrowthventures.atlassian.net/jira/software/projects/CON/boards/34 | CON |

## Structure

See [STRUCTURE.md](STRUCTURE.md) for file-level descriptions.

```
infra/
├── bootstrap/                 # One-time state backend setup
│   └── main.tf
├── modules/
│   ├── alb/                   # Application Load Balancer
│   ├── ecs_cluster/           # ECS cluster, task definitions, IAM, logs
│   ├── rds/                   # RDS PostgreSQL instance
│   ├── security_groups/       # Per-service security groups
│   └── vpc/                   # VPC, subnets, NAT gateway
└── staging/                   # Staging environment root module
    ├── main.tf
    ├── variables.tf
    └── terraform.tfvars        # Not committed
```

## Environments

| Environment | Path | Region | State key |
|-------------|------|--------|-----------|
| staging | `staging/` | `eu-north-1` | `staging/terraform.tfstate` |

## Environment Variables injected per service

### auth-service
| Variable | Source | Notes |
|----------|--------|-------|
| `AUTH_POSTGRES_HOST` | `rds_endpoint` | RDS instance address |
| `AUTH_POSTGRES_PORT` | hardcoded | `5432` |
| `AUTH_POSTGRES_DB` | hardcoded | `auth_db` |
| `AUTH_POSTGRES_USER` | hardcoded | `auth_user` |
| `AUTH_POSTGRES_PASSWORD` | Secrets Manager | `ocn/{env}/auth-service:POSTGRES_PASSWORD` |
| `AUTH_ADMIN_API_KEY` | Secrets Manager | `ocn/{env}/auth-service:ADMIN_API_KEY` |

### news-retrieval
| Variable | Source | Notes |
|----------|--------|-------|
| `POSTGRES_HOST` | `rds_endpoint` | |
| `POSTGRES_PORT` | hardcoded | `5432` |
| `POSTGRES_DB` | hardcoded | `news_retrieval_db` |
| `POSTGRES_USER` | hardcoded | `news_user` |
| `POSTGRES_PASSWORD` | Secrets Manager | `ocn/{env}/news-retrieval:POSTGRES_PASSWORD` |
| `AUTH_SERVICE_URL` | hardcoded | `http://auth-service.{env}.ocn.internal:8001` |
| `OPENROUTER_API_KEY` | Secrets Manager | `ocn/{env}/news-retrieval:OPENROUTER_API_KEY` |
| `OPENROUTER_MODEL` | hardcoded | `openrouter/elephant-alpha` |

### signal-detection
| Variable | Source | Notes |
|----------|--------|-------|
| `POSTGRES_HOST` | `rds_endpoint` | |
| `POSTGRES_PORT` | hardcoded | `5432` |
| `POSTGRES_DB` | hardcoded | `signal_detection_db` |
| `POSTGRES_USER` | hardcoded | `signal_user` |
| `POSTGRES_PASSWORD` | Secrets Manager | `ocn/{env}/signal-detection:POSTGRES_PASSWORD` |
| `AUTH_SERVICE_URL` | hardcoded | `http://auth-service.{env}.ocn.internal:8001` |
| `NEWS_RETRIEVAL_URL` | hardcoded | `http://news-retrieval.{env}.ocn.internal:8000` |
| `QDRANT_HOST` | `qdrant_host` var | |
| `QDRANT_PORT` | hardcoded | `6333` |
| `LANGFUSE_HOST` | hardcoded | `https://cloud.langfuse.com` |
| `OPENROUTER_API_KEY` | Secrets Manager | `ocn/{env}/signal-detection:OPENROUTER_API_KEY` |
| `QDRANT_API_KEY` | Secrets Manager | `ocn/{env}/signal-detection:QDRANT_API_KEY` |
| `LANGFUSE_SECRET_KEY` | Secrets Manager | `ocn/{env}/signal-detection:LANGFUSE_SECRET_KEY` |
| `LANGFUSE_PUBLIC_KEY` | Secrets Manager | `ocn/{env}/signal-detection:LANGFUSE_PUBLIC_KEY` |

## Guidance

- Read only the docs relevant to your task
- Use the Jira board (project key `CON`) to track and reference cards
- All secrets must exist in Secrets Manager before `terraform apply` — ECS task launch fails at runtime if a `valueFrom` ARN cannot be resolved
- When adding a new service, add its security group in `modules/security_groups`, its task definition and ECS service in `modules/ecs_cluster/services.tf`, and its log group in `modules/ecs_cluster/logs.tf`

## Maintenance

- Do not modify the Jira Board, Guidance, or Maintenance sections unless explicitly asked
- Keep the Environment Variables tables above in sync with `modules/ecs_cluster/services.tf` whenever env vars are added, renamed, or removed
