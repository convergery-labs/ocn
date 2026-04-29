FROM python:3.12-slim AS base

WORKDIR /app

COPY news-retrieval/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/src/ /app/shared/
COPY news-retrieval/src/ /app/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/shared

CMD ["python", "__main__.py", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS dev

FROM base AS test
ENV PYTHONPATH=/app:/app/shared
COPY news-retrieval/requirements-test.txt .
RUN pip install --no-cache-dir -r requirements-test.txt
COPY news-retrieval/tests/ tests/
COPY news-retrieval/pyproject.toml .
CMD ["pytest", "tests/", "-v"]
