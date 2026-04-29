terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  backend "s3" {
    bucket         = "ocn-terraform-state"
    key            = "staging/terraform.tfstate"
    region         = "eu-north-1"
    dynamodb_table = "ocn-terraform-lock"
    encrypt        = true
  }
}

provider "aws" {
  region = "eu-north-1"
}

module "vpc" {
  source   = "../modules/vpc"
  env      = "staging"
  vpc_cidr = "10.0.0.0/16"
  azs      = ["eu-north-1a", "eu-north-1b"]
}

module "security_groups" {
  source = "../modules/security_groups"
  env    = "staging"
  vpc_id = module.vpc.vpc_id
}

module "rds" {
  source             = "../modules/rds"
  env                = "staging"
  private_subnet_ids = module.vpc.private_subnet_ids
  rds_sg_id          = module.security_groups.rds_sg_id
  instance_class     = "db.t4g.small"
  db_master_user     = "master"
  db_master_password = var.db_master_password
}

module "ecs_cluster" {
  source                = "../modules/ecs_cluster"
  env                   = "staging"
  vpc_id                = module.vpc.vpc_id
  public_subnet_ids     = module.vpc.public_subnet_ids
  private_subnet_ids    = module.vpc.private_subnet_ids
  rds_endpoint          = module.rds.endpoint
  ecr_registry          = var.ecr_registry
  aws_region            = "eu-north-1"
  aws_account_id        = var.aws_account_id
  gateway_sg_id         = module.security_groups.gateway_sg_id
  auth_sg_id            = module.security_groups.auth_sg_id
  news_sg_id            = module.security_groups.news_sg_id
  signal_sg_id          = module.security_groups.signal_sg_id
  api_gateway_tg_arn    = module.alb.api_gateway_tg_arn
  qdrant_host           = var.qdrant_host
}

module "alb" {
  source            = "../modules/alb"
  env               = "staging"
  vpc_id            = module.vpc.vpc_id
  public_subnet_ids = module.vpc.public_subnet_ids
  alb_sg_id         = module.security_groups.alb_sg_id
}

resource "aws_ecr_repository" "api_gateway" {
  name                 = "ocn/api-gateway"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}
