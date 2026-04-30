FROM python:3.12-slim AS base

WORKDIR /app

COPY ocn-agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ocn-agent/src/ /app/

ENV PYTHONUNBUFFERED=1

CMD ["python", "__main__.py", "--host", "0.0.0.0", "--port", "8003"]

FROM base AS dev
