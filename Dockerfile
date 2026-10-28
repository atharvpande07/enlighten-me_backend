# Multi-stage lightweight production Dockerfile for Enlighten Me FastAPI Backend
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency manifest
COPY requirements.txt .

# Install dependencies into wheels directory
RUN pip install --no-cache-dir --upgrade pip && \
    pip wheel --no-cache-dir --no-deps --wheel-dir /build/wheels -r requirements.txt


# Final Runtime Stage
FROM python:3.12-slim AS runner

WORKDIR /app

# Install minimal runtime libraries (curl for healthchecks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built wheels from builder
COPY --from=builder /build/wheels /wheels
COPY --from=builder /build/requirements.txt .
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Create non-root application user for container security
RUN groupadd -r appgroup && useradd -r -g appgroup -s /sbin/nologin appuser

# Copy application source code
COPY app/ ./app/

# Set ownership
RUN chown -R appuser:appgroup /app

USER appuser

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    ENVIRONMENT=production

EXPOSE 8000

# Healthcheck checking the diagnostic endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/api/v1/health || exit 1

# Launch ASGI server with 180s timeout keep-alive boundary
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--timeout-keep-alive", "180"]
