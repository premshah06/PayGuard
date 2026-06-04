FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir aiokafka==0.10.0 asyncpg==0.29.0 httpx==0.25.2

COPY consumer/ ./consumer/
COPY producer/ ./producer/

CMD ["python", "-m", "consumer.consumer"]
