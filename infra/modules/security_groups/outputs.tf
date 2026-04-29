output "alb_sg_id" {
  value = aws_security_group.alb.id
}


output "gateway_sg_id" {
  value = aws_security_group.api_gateway.id
}


output "news_sg_id" {
  value = aws_security_group.news_retrieval.id
}


output "signal_sg_id" {
  value = aws_security_group.signal_detection.id
}


output "auth_sg_id" {
  value = aws_security_group.auth_service.id
}


output "rds_sg_id" {
  value = aws_security_group.rds.id
}
