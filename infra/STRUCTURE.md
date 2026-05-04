# Structure

## Root

| Directory | Purpose |
|-----------|---------|
| `bootstrap/` | One-time setup: S3 bucket and DynamoDB table for Terraform remote state |
| `modules/` | Reusable Terraform modules; each environment wires them together |
| `staging/` | Staging environment root module |

## bootstrap

Run once per AWS account to provision remote state storage before any environment can be applied.

| File | Purpose |
|------|---------|
| `main.tf` | S3 bucket (versioned) + DynamoDB lock table (`ocn-terraform-state` / `ocn-terraform-lock`) |

## modules

### alb

Application Load Balancer. Exposes `api-gateway` publicly on port 80.

| File | Purpose |
|------|---------|
| `main.tf` | ALB, `api-gateway` target group (port 8004, health check `/health`), HTTP listener |
| `outputs.tf` | `api_gateway_tg_arn`, `alb_dns_name` |
| `variables.tf` | `env`, `vpc_id`, `public_subnet_ids`, `alb_sg_id` |

### ecs_cluster

ECS Fargate cluster, task definitions, services, service discovery, IAM, logs, and CI/CD roles.

| File | Purpose |
|------|---------|
| `main.tf` | ECS cluster (Container Insights on) + private DNS namespace (`{env}.ocn.internal`) |
| `services.tf` | Task definitions and ECS services for all four services; nightly `promote-corpus` scheduled task |
| `iam.tf` | Task execution role (ECR + Secrets Manager read); GitHub Actions OIDC role (ECR push + ECS deploy) |
| `logs.tf` | CloudWatch log groups for each service (30-day retention) |
| `variables.tf` | `env`, `vpc_id`, `public_subnet_ids`, `private_subnet_ids`, `rds_endpoint`, `ecr_registry`, `image_tag`, `aws_region`, `aws_account_id`, `gateway_sg_id`, `{auth,news,signal}_sg_id`, `api_gateway_tg_arn`, `qdrant_host` |

### rds

Single shared RDS PostgreSQL 16 instance. Each service uses its own database and user; credentials are managed separately via Secrets Manager.

| File | Purpose |
|------|---------|
| `main.tf` | RDS instance (`gp3`, 20 GB, encrypted, private subnet group) |
| `outputs.tf` | `endpoint` |
| `variables.tf` | `env`, `private_subnet_ids`, `rds_sg_id`, `instance_class`, `db_master_user`, `db_master_password` |

### security_groups

One security group per service. Ingress rules enforce least-privilege service-to-service access.

| File | Purpose |
|------|---------|
| `main.tf` | `alb` (80 public), `api-gateway` (8004 from ALB), `news-retrieval` (8000 from gateway), `signal-detection` (8002 from gateway), `auth-service` (8001 from gateway + news + signal), `rds` (5432 from auth + news + signal) |
| `outputs.tf` | `{alb,gateway,auth,news,signal,rds}_sg_id` |
| `variables.tf` | `env`, `vpc_id` |

### vpc

VPC with two public and two private subnets across two AZs. Private subnets route outbound via NAT.

| File | Purpose |
|------|---------|
| `main.tf` | VPC (`10.0.0.0/16`), public/private subnets, internet gateway, NAT gateway, route tables |
| `outputs.tf` | `vpc_id`, `public_subnet_ids`, `private_subnet_ids` |
| `variables.tf` | `env`, `vpc_cidr`, `azs` |

## staging

| File | Purpose |
|------|---------|
| `main.tf` | Wires all modules together for the staging environment (`eu-north-1`); includes `aws_ecr_repository.api_gateway` |
| `frontend.tf` | S3 bucket + CloudFront distribution for frontend SPA; GitHub Actions IAM extension; outputs `frontend_url` |
| `variables.tf` | `db_master_password` (sensitive), `ecr_registry`, `aws_account_id`, `qdrant_host` |
| `terraform.tfvars` | Staging variable values — not committed |
