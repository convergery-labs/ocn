resource "aws_lb" "main" {
  name               = "${var.env}-ocn-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [var.alb_sg_id]
  subnets            = var.public_subnet_ids
}


resource "aws_lb_target_group" "api_gateway" {
  name        = "${var.env}-api-gateway"
  port        = 8004
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"
  health_check {
    path                = "/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
  }
}


resource "aws_lb_target_group" "research_universe" {
  name        = "${var.env}-research-universe"
  port        = 8007
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"
  health_check {
    path                = "/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
  }
}


resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api_gateway.arn
  }
}


# Route /universe/* to research-universe (higher priority than the default rule)
resource "aws_lb_listener_rule" "research_universe" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.research_universe.arn
  }

  condition {
    path_pattern {
      values = ["/universe/*", "/universe"]
    }
  }
}
