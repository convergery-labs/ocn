output "news_retrieval_tg_arn" {
  value = aws_lb_target_group.news_retrieval.arn
}


output "alb_dns_name" {
  value = aws_lb.main.dns_name
}
