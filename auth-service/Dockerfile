FROM python:3.12-slim AS base

WORKDIR /app

COPY auth-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/src/ /app/shared/
COPY auth-service/src/ /app/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/shared

CMD ["python", "__main__.py", "--host", "0.0.0.0", "--port", "8001"]

FROM base AS dev

FROM base AS test
COPY auth-service/requirements-test.txt .
RUN pip install --no-cache-dir -r requirements-test.txt
COPY auth-service/tests/ tests/
COPY auth-service/pyproject.toml .
CMD ["pytest", "tests/", "-v"]
