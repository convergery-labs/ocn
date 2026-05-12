FROM python:3.11-slim AS base

WORKDIR /app

COPY research-universe/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY research-universe/src/ src/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

CMD ["python", "-m", "src", "serve", "--host", "0.0.0.0", "--port", "8006"]


FROM base AS dev

CMD ["python", "-m", "src", "serve", "--host", "0.0.0.0", "--port", "8006", "--reload"]


FROM base AS test

COPY research-universe/requirements-test.txt requirements-test.txt
RUN pip install --no-cache-dir -r requirements-test.txt

COPY research-universe/tests/ tests/
COPY research-universe/pyproject.toml pyproject.toml

CMD ["pytest", "tests/", "-v"]
