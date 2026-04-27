variable "env" {
  type = string
}


variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}


variable "rds_endpoint" {
  type = string
}


variable "ecr_registry" {
  type = string
}


variable "image_tag" {
  type    = string
  default = "latest"
}


variable "aws_region" {
  type = string
}


variable "aws_account_id" {
  type = string
}


variable "auth_sg_id" {
  type = string
}


variable "news_sg_id" {
  type = string
}


variable "signal_sg_id" {
  type = string
}


variable "news_retrieval_tg_arn" {
  type = string
}


variable "qdrant_host" {
  type = string
}

