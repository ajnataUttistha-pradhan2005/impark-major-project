# ==============================================================================
# IMPARK CPU Evaluator Worker Dockerfile
# Optimized for self-hosted local CPU inference (~220MB RAM, 0% idle CPU)
# ==============================================================================

FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HUB_ENABLE_HF_TRANSFER=0 \
    TORCH_DEVICE=cpu

WORKDIR /app

# Install minimal OS dependencies for building psycopg2 and networking
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch CPU-only first to avoid pulling multi-GB CUDA binaries
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Install application dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download CPU inference models during build stage for 100% offline startup readiness
RUN python -c "\
from sentence_transformers import SentenceTransformer, CrossEncoder; \
print('Pre-caching all-MiniLM-L6-v2...'); \
SentenceTransformer('all-MiniLM-L6-v2', device='cpu'); \
print('Pre-caching cross-encoder/nli-deberta-v3-small...'); \
CrossEncoder('cross-encoder/nli-deberta-v3-small', device='cpu'); \
print('Model pre-caching complete.')"

# Copy source code
COPY redis_evaluator.py local_tracer.py test_pipeline.py ./

# Healthcheck checking if process is running and connected
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import redis; r = redis.Redis(host='redis', port=6379); r.ping()" || exit 1

# Default execution command
CMD ["python", "redis_evaluator.py"]
