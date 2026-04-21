# TODO: Implement once auth-service is built
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/

CMD ["python", "-m", "src", "--host", "0.0.0.0", "--port", "8001"]
