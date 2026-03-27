FROM python:3.12-slim

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir \
    "fastapi>=0.115" "uvicorn>=0.30" "python-multipart>=0.0.9" \
    "httpx>=0.27" "websockets>=13" "Pillow>=10" "fal-client>=0.5"

COPY server.py comfyui_client.py cloud_router.py queue_manager.py ./
COPY workflows/ ./workflows/

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
