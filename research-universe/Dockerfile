FROM python:3.12-slim AS base

WORKDIR /app

COPY research-universe/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/src/ /app/shared/
COPY research-universe/src/ src/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src:/app/shared

CMD ["python", "-m", "src", "serve", "--host", "0.0.0.0", "--port", "8007"]

FROM base AS dev
