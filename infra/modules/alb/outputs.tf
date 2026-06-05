output "api_gateway_tg_arn" {
  value = aws_lb_target_group.api_gateway.arn
}


output "alb_dns_name" {
  value = aws_lb.main.dns_name
}


output "research_universe_tg_arn" {
  value = aws_lb_target_group.research_universe.arn
}
