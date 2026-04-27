variable "env" {
  type = string
}


variable "private_subnet_ids" {
  type = list(string)
}


variable "rds_sg_id" {
  type = string
}


variable "instance_class" {
  type    = string
  default = "db.t4g.small"
}


variable "db_master_user" {
  type = string
}


variable "db_master_password" {
  type      = string
  sensitive = true
}
