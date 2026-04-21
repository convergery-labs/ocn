# TODO: Implement once signal-detection is built
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/

CMD ["python", "-m", "src", "--host", "0.0.0.0", "--port", "8002"]
