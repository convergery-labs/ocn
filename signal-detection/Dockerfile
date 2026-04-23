FROM python:3.12-slim AS base

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

CMD ["python", "-m", "src", "--host", "0.0.0.0", "--port", "8002"]

FROM base AS dev
