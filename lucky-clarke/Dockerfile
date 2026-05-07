FROM python:3.11-slim AS base

WORKDIR /app

COPY lucky-clarke/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY lucky-clarke/src/ src/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

CMD ["python", "-m", "src", "serve", "--host", "0.0.0.0", "--port", "8005"]


FROM base AS dev

CMD ["python", "-m", "src", "serve", "--host", "0.0.0.0", "--port", "8005", "--reload"]


FROM base AS test

ENV PYTHONPATH=/app/src
COPY lucky-clarke/requirements-test.txt requirements-test.txt
RUN pip install --no-cache-dir -r requirements-test.txt

COPY lucky-clarke/tests/ tests/
COPY lucky-clarke/pyproject.toml pyproject.toml

CMD ["pytest", "tests/", "-v"]
