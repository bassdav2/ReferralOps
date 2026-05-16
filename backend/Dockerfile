FROM python:3.12-slim

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      tesseract-ocr \
      tesseract-ocr-deu \
      tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml /app/pyproject.toml
COPY backend /app/backend
COPY configs /app/configs
COPY demos /app/demos
ARG INSTALL_LOCAL_EMBEDDINGS=false
RUN if [ "$INSTALL_LOCAL_EMBEDDINGS" = "true" ]; then \
      pip install --no-cache-dir -e ".[local-embeddings]"; \
    else \
      pip install --no-cache-dir -e .; \
    fi
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
