FROM python:3.12-slim AS base

WORKDIR /app

COPY api-gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api-gateway/src/ /app/

ENV PYTHONUNBUFFERED=1

CMD ["python", "__main__.py", "--host", "0.0.0.0", "--port", "8004"]

FROM base AS dev

FROM base AS test
COPY api-gateway/requirements-test.txt .
RUN pip install --no-cache-dir -r requirements-test.txt
COPY api-gateway/tests/ tests/
COPY api-gateway/pyproject.toml .
CMD ["pytest", "tests/", "-v"]
