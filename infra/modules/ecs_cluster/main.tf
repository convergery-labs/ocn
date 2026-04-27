resource "aws_ecs_cluster" "main" {
  name = "${var.env}-ocn-cluster"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}


resource "aws_service_discovery_private_dns_namespace" "main" {
  name = "${var.env}.ocn.internal"
  vpc  = var.vpc_id
}


output "cluster_id" {
  value = aws_ecs_cluster.main.id
}


output "cluster_arn" {
  value = aws_ecs_cluster.main.arn
}


output "namespace_id" {
  value = aws_service_discovery_private_dns_namespace.main.id
}
