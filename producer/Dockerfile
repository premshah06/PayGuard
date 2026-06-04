FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir aiokafka==0.10.0

COPY producer/ ./producer/

CMD ["python", "-m", "producer.generator"]
