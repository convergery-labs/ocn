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


resource "aws_security_group" "signal_detection_agent" {
  name   = "${var.env}-signal-detection-agent"
  vpc_id = var.vpc_id
  ingress {
    from_port = 8003
    to_port   = 8003
    protocol  = "tcp"
    security_groups = [
      aws_security_group.api_gateway.id,
      aws_security_group.signal_herald.id,
    ]
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
      aws_security_group.signal_detection_agent.id,
      aws_security_group.lucky_clarke.id,
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
    from_port = 8002
    to_port   = 8002
    protocol  = "tcp"
    security_groups = [
      aws_security_group.api_gateway.id,
      aws_security_group.lucky_clarke.id,
    ]
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


resource "aws_security_group" "lucky_clarke" {
  name   = "${var.env}-lucky-clarke"
  vpc_id = var.vpc_id
  ingress {
    from_port   = 8005
    to_port     = 8005
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}


resource "aws_security_group" "research_universe" {
  name   = "${var.env}-research-universe"
  vpc_id = var.vpc_id
  ingress {
    from_port = 8007
    to_port   = 8007
    protocol  = "tcp"
    security_groups = [
      aws_security_group.alb.id,
      aws_security_group.news_retrieval.id,
    ]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}


data "aws_security_group" "bastion" {
  name   = "${var.env}-bastion"
  vpc_id = var.vpc_id
}

resource "aws_security_group" "signal_herald" {
  name   = "${var.env}-signal-herald"
  vpc_id = var.vpc_id
  ingress {
    from_port   = 8006
    to_port     = 8006
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# signal_detection_agent and news_retrieval each need an ingress rule
# referencing the OTHER's security group id (news_retrieval -> 8000, for
# signal-detection-agent's own outbound API calls to news-retrieval;
# signal_detection_agent -> 8003, for news-retrieval's webhook callback
# on run completion - see controllers/run.py's _fire_webhook). Two
# resources with inline ingress blocks that reference each other's id
# create a dependency cycle Terraform can't resolve, so this one
# direction is pulled out into a standalone rule instead - the
# news_retrieval resource's own inline ingress (referencing
# signal_detection_agent.id for port 8000) is the one direction that's
# safe to keep inline, since signal_detection_agent's own inline ingress
# no longer references news_retrieval back.
#
# Confirmed live: this rule was missing entirely before - the webhook
# callback was a guaranteed TCP-level connection timeout on every
# attempt (verified via a raw socket connect test from inside the real
# running news-retrieval task to the real, live signal-detection-agent
# IP:port - DNS resolution was correct, the connection itself timed out),
# not a transient network blip. The 05:00 UTC fallback schedule caught
# the resulting gap with no data loss, which is why this went unnoticed
# until checked directly.
resource "aws_security_group_rule" "news_retrieval_to_signal_detection_agent" {
  type                     = "ingress"
  from_port                = 8003
  to_port                  = 8003
  protocol                 = "tcp"
  security_group_id        = aws_security_group.signal_detection_agent.id
  source_security_group_id = aws_security_group.news_retrieval.id
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
      aws_security_group.signal_detection_agent.id,
      aws_security_group.research_universe.id,
      data.aws_security_group.bastion.id,
    ]
  }
}
