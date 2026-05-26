FROM python:3.11-slim AS base

WORKDIR /app

COPY signal-herald/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY signal-herald/src/ src/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

CMD ["python", "-m", "src", "serve", "--host", "0.0.0.0", "--port", "8006"]


FROM base AS dev

CMD ["python", "-m", "src", "serve", "--host", "0.0.0.0", "--port", "8006", "--reload"]
