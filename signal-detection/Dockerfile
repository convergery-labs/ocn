FROM python:3.12-slim AS base

WORKDIR /app

COPY signal-detection/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    python -m spacy download en_core_web_lg

COPY shared/src/ /app/shared/
COPY signal-detection/src/ src/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src:/app/shared

CMD ["python", "-m", "src", "serve", "--host", "0.0.0.0", "--port", "8002"]

FROM base AS dev

FROM base AS test
ENV PYTHONPATH=/app/src:/app/shared
COPY signal-detection/requirements-test.txt .
RUN pip install --no-cache-dir -r requirements-test.txt
COPY signal-detection/tests/ tests/
COPY signal-detection/pyproject.toml .
CMD ["pytest", "tests/", "-v"]
