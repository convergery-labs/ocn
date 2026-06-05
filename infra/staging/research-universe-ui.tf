resource "aws_s3_bucket" "research_universe_ui" {
  bucket = "ocn-staging-research-universe-ui"
}

resource "aws_s3_bucket_versioning" "research_universe_ui" {
  bucket = aws_s3_bucket.research_universe_ui.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "research_universe_ui" {
  bucket = aws_s3_bucket.research_universe_ui.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "research_universe_ui" {
  bucket = aws_s3_bucket.research_universe_ui.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_cloudfront_origin_access_control" "research_universe_ui" {
  name                              = "ocn-staging-research-universe-ui-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "research_universe_ui" {
  enabled             = true
  default_root_object = "index.html"
  price_class         = "PriceClass_100"

  # S3 origin - serves the React SPA
  origin {
    domain_name              = aws_s3_bucket.research_universe_ui.bucket_regional_domain_name
    origin_id                = "s3-ocn-staging-research-universe-ui"
    origin_access_control_id = aws_cloudfront_origin_access_control.research_universe_ui.id
  }

  # ALB origin - serves /universe/* API traffic
  origin {
    domain_name = module.alb.alb_dns_name
    origin_id   = "alb-staging-universe-api"
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # /universe/* → ALB, never cached
  ordered_cache_behavior {
    path_pattern             = "/universe/*"
    target_origin_id         = "alb-staging-universe-api"
    viewer_protocol_policy   = "https-only"
    allowed_methods          = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = local.cache_policy_disabled
    origin_request_policy_id = local.origin_request_policy_all_no_host
  }

  # Default behavior - serves the SPA from S3
  default_cache_behavior {
    target_origin_id       = "s3-ocn-staging-research-universe-ui"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }
  }

  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
  }

  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

resource "aws_s3_bucket_policy" "research_universe_ui" {
  bucket = aws_s3_bucket.research_universe_ui.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.research_universe_ui.arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.research_universe_ui.arn
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "github_actions_research_universe_ui" {
  name = "ocn-github-actions-research-universe-ui"
  role = data.aws_iam_role.github_actions.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.research_universe_ui.arn,
          "${aws_s3_bucket.research_universe_ui.arn}/*"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["cloudfront:CreateInvalidation"]
        Resource = aws_cloudfront_distribution.research_universe_ui.arn
      }
    ]
  })
}

output "research_universe_ui_url" {
  value = "https://${aws_cloudfront_distribution.research_universe_ui.domain_name}"
}
