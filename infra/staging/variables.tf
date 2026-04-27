variable "db_master_password" {
  type      = string
  sensitive = true
}

variable "ecr_registry" {
  type = string
}

variable "aws_account_id" {
  type = string
}

variable "qdrant_host" {
  type = string
}
