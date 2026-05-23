FROM python:3.12-slim AS base

WORKDIR /app

COPY signal-detection-agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/src/ /app/shared/
COPY signal-detection-agent/src/ src/
COPY signal-detection-agent/prompts/ prompts/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src:/app/shared

CMD ["python", "-m", "src", "serve", "--host", "0.0.0.0", "--port", "8003"]

FROM base AS dev

FROM base AS test
ENV PYTHONPATH=/app/src:/app/shared
COPY signal-detection-agent/requirements-test.txt .
RUN pip install --no-cache-dir -r requirements-test.txt
COPY signal-detection-agent/tests/ tests/
COPY signal-detection-agent/pyproject.toml .
CMD ["pytest", "tests/", "-v"]
