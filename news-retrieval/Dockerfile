FROM python:3.12-slim

WORKDIR /app

COPY src/ /app

RUN pip install --no-cache-dir \
    fastapi>=0.109.0 \
    uvicorn>=0.27.0 \
    pydantic>=2.6.0 \
    openai>=1.0.0 \
    click>=8.1.7 \
    feedparser>=6.0.11 \
    httpx>=0.27.0 \
    psycopg2-binary>=2.9.0

ENV PYTHONUNBUFFERED=1

CMD ["python", "__main__.py", "--host", "0.0.0.0", "--port", "8000"]