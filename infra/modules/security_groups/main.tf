resource "aws_security_group" "alb" {
  name   = "${var.env}-alb"
  vpc_id = var.vpc_id
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}


resource "aws_security_group" "api_gateway" {
  name   = "${var.env}-api-gateway"
  vpc_id = var.vpc_id
  ingress {
    from_port       = 8004
    to_port         = 8004
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}


resource "aws_security_group" "news_retrieval" {
  name   = "${var.env}-news-retrieval"
  vpc_id = var.vpc_id
  ingress {
    from_port = 8000
    to_port   = 8000
    protocol  = "tcp"
    security_groups = [
      aws_security_group.api_gateway.id,
      aws_security_group.signal_detection.id,
    ]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}


resource "aws_security_group" "signal_detection" {
  name   = "${var.env}-signal-detection"
  vpc_id = var.vpc_id
  ingress {
    from_port       = 8002
    to_port         = 8002
    protocol        = "tcp"
    security_groups = [aws_security_group.api_gateway.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}


resource "aws_security_group" "auth_service" {
  name   = "${var.env}-auth-service"
  vpc_id = var.vpc_id
  ingress {
    from_port = 8001
    to_port   = 8001
    protocol  = "tcp"
    security_groups = [
      aws_security_group.api_gateway.id,
      aws_security_group.news_retrieval.id,
      aws_security_group.signal_detection.id,
    ]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}


resource "aws_security_group" "rds" {
  name   = "${var.env}-rds"
  vpc_id = var.vpc_id
  ingress {
    from_port = 5432
    to_port   = 5432
    protocol  = "tcp"
    security_groups = [
      aws_security_group.auth_service.id,
      aws_security_group.news_retrieval.id,
      aws_security_group.signal_detection.id,
    ]
  }
}
