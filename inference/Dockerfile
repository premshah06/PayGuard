FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir \
    fastapi==0.104.1 \
    uvicorn[standard]==0.24.0 \
    numpy==1.26.2 \
    onnxruntime==1.16.3 \
    scipy==1.11.4 \
    pydantic==2.5.2

COPY consumer/ ./consumer/
COPY inference/ ./inference/
# Model artefacts are mounted at runtime from the ml/ volume.

CMD ["uvicorn", "inference.app:app", "--host", "0.0.0.0", "--port", "8000"]
