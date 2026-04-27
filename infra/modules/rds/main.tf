resource "aws_db_subnet_group" "main" {
  name       = "${var.env}-ocn-rds-subnet-group"
  subnet_ids = var.private_subnet_ids
}


resource "aws_db_instance" "postgres" {
  identifier        = "${var.env}-ocn-postgres"
  engine            = "postgres"
  engine_version    = "16"
  instance_class    = var.instance_class
  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true


  db_name  = "postgres"
  username = var.db_master_user
  password = var.db_master_password


  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [var.rds_sg_id]
  publicly_accessible    = false
  skip_final_snapshot    = true
}
