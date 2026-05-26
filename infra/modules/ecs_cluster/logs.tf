resource "aws_cloudwatch_log_group" "auth_service" {
  name              = "/ecs/${var.env}/auth-service"
  retention_in_days = 30
}


resource "aws_cloudwatch_log_group" "news_retrieval" {
  name              = "/ecs/${var.env}/news-retrieval"
  retention_in_days = 30
}


resource "aws_cloudwatch_log_group" "signal_detection" {
  name              = "/ecs/${var.env}/signal-detection"
  retention_in_days = 30
}


resource "aws_cloudwatch_log_group" "api_gateway" {
  name              = "/ecs/${var.env}/api-gateway"
  retention_in_days = 30
}


resource "aws_cloudwatch_log_group" "lucky_clarke" {
  name              = "/ecs/${var.env}/lucky-clarke"
  retention_in_days = 30
}


resource "aws_cloudwatch_log_group" "signal_detection_agent" {
  name              = "/ecs/${var.env}/signal-detection-agent"
  retention_in_days = 30
}


resource "aws_cloudwatch_log_group" "signal_herald" {
  name              = "/ecs/${var.env}/signal-herald"
  retention_in_days = 30
}
