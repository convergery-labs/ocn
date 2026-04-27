ECR ?= 340482407167.dkr.ecr.eu-north-1.amazonaws.com
PLATFORM := linux/amd64
SERVICES := auth-service news-retrieval signal-detection
BASTION_ID ?= i-08490aaab61a822d2
RDS_HOST ?= staging-ocn-postgres.c506a00ggbbn.eu-north-1.rds.amazonaws.com
RDS_LOCAL_PORT ?= 5433

.PHONY: ecr-login build-auth build-news build-signal build-all \
        push-auth push-news push-signal push-all tunnel-rds

# Authenticate Docker to ECR
ecr-login:
	AWS_PROFILE=local-dev aws ecr get-login-password --region eu-north-1 \
	  | docker login --username AWS --password-stdin $(ECR)

# Per-service build targets
build-auth:
	docker build --platform $(PLATFORM) --target base -t $(ECR)/ocn/auth-service:latest auth-service/

build-news:
	docker build --platform $(PLATFORM) --target base -t $(ECR)/ocn/news-retrieval:latest news-retrieval/

build-signal:
	docker build --platform $(PLATFORM) --target base -t $(ECR)/ocn/signal-detection:latest signal-detection/

build-all: build-auth build-news build-signal

# Per-service push targets (build + push)
push-auth: build-auth
	docker push $(ECR)/ocn/auth-service:latest

push-news: build-news
	docker push $(ECR)/ocn/news-retrieval:latest

push-signal: build-signal
	docker push $(ECR)/ocn/signal-detection:latest

push-all: ecr-login build-all
	docker push $(ECR)/ocn/auth-service:latest
	docker push $(ECR)/ocn/news-retrieval:latest
	docker push $(ECR)/ocn/signal-detection:latest

# Tunnel RDS to localhost via SSM — requires SSM Session Manager plugin
# https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html
# Connect DBeaver to localhost:$(RDS_LOCAL_PORT) once this is running
tunnel-rds:
	AWS_PROFILE=local-dev aws ssm start-session \
	  --target $(BASTION_ID) \
	  --document-name AWS-StartPortForwardingSessionToRemoteHost \
	  --parameters '{"host":["$(RDS_HOST)"],"portNumber":["5432"],"localPortNumber":["$(RDS_LOCAL_PORT)"]}'
