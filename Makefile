ECR ?= 340482407167.dkr.ecr.eu-north-1.amazonaws.com
PLATFORM := linux/amd64
SERVICES := auth-service news-retrieval signal-detection api-gateway lucky-clarke
BASTION_ID ?= i-08490aaab61a822d2
RDS_HOST ?= staging-ocn-postgres.c506a00ggbbn.eu-north-1.rds.amazonaws.com
RDS_LOCAL_PORT ?= 5433
FRONTEND_BUCKET ?= ocn-staging-frontend
CLOUDFRONT_DISTRIBUTION_ID ?= EGJ8FLEL3FECL
VITE_API_BASE_URL ?= https://d27leazxx8pioq.cloudfront.net

.PHONY: ecr-login build-auth build-news build-signal build-gateway build-lucky build-all \
        push-auth push-news push-signal push-gateway push-lucky push-all tunnel-rds \
        build-frontend deploy-frontend

# Authenticate Docker to ECR
ecr-login:
	aws ecr get-login-password --region eu-north-1 \
	  | docker login --username AWS --password-stdin $(ECR)

# Per-service build targets (build context is repo root; Dockerfiles use root-relative COPY paths)
build-auth:
	docker build --platform $(PLATFORM) --target base \
	  -f auth-service/Dockerfile \
	  -t $(ECR)/ocn/auth-service:latest .

build-news:
	docker build --platform $(PLATFORM) --target base \
	  -f news-retrieval/Dockerfile \
	  -t $(ECR)/ocn/news-retrieval:latest .

build-signal:
	docker build --platform $(PLATFORM) --target base \
	  -f signal-detection/Dockerfile \
	  -t $(ECR)/ocn/signal-detection:latest .

build-gateway:
	docker build --platform $(PLATFORM) --target base \
	  -f api-gateway/Dockerfile \
	  -t $(ECR)/ocn/api-gateway:latest .

build-lucky:
	docker build --platform $(PLATFORM) --target base \
	  -f lucky-clarke/Dockerfile \
	  -t $(ECR)/ocn/lucky-clarke:latest .

build-all: build-auth build-news build-signal build-gateway build-lucky

# Per-service push targets (build + push)
push-auth: ecr-login build-auth
	docker push $(ECR)/ocn/auth-service:latest

push-news: ecr-login build-news
	docker push $(ECR)/ocn/news-retrieval:latest

push-signal: ecr-login build-signal
	docker push $(ECR)/ocn/signal-detection:latest

push-gateway: ecr-login build-gateway
	docker push $(ECR)/ocn/api-gateway:latest

push-lucky: ecr-login build-lucky
	docker push $(ECR)/ocn/lucky-clarke:latest

push-all: ecr-login build-all
	docker push $(ECR)/ocn/auth-service:latest
	docker push $(ECR)/ocn/news-retrieval:latest
	docker push $(ECR)/ocn/signal-detection:latest
	docker push $(ECR)/ocn/api-gateway:latest
	docker push $(ECR)/ocn/lucky-clarke:latest

# Build and deploy frontend to S3 + invalidate CloudFront cache
build-frontend:
	cd frontend && npm ci && VITE_API_BASE_URL=$(VITE_API_BASE_URL) npm run build

deploy-frontend: build-frontend
	aws s3 sync frontend/dist/ s3://$(FRONTEND_BUCKET) --delete
	aws cloudfront create-invalidation \
	  --distribution-id $(CLOUDFRONT_DISTRIBUTION_ID) \
	  --paths "/*"

# Tunnel RDS to localhost via SSM - requires SSM Session Manager plugin
# https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html
# Connect DBeaver to localhost:$(RDS_LOCAL_PORT) once this is running
tunnel-rds:
	aws ssm start-session \
	  --target $(BASTION_ID) \
	  --document-name AWS-StartPortForwardingSessionToRemoteHost \
	  --parameters '{"host":["$(RDS_HOST)"],"portNumber":["5432"],"localPortNumber":["$(RDS_LOCAL_PORT)"]}'
