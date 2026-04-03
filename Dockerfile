# YouTube Channel Cloner — Production Dockerfile
# Multi-stage build for smaller final image

# ── Stage 1: Dependencies ─────────────────────────────────
FROM python:3.11-slim AS deps

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Runtime ──────────────────────────────────────
FROM python:3.11-slim

LABEL maintainer="YT Cloner Team"
LABEL description="YouTube Channel Cloner - AI-powered channel analysis and content generation"
LABEL version="3.0"

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl ca-certificates && \
    curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp && \
    chmod a+rx /usr/local/bin/yt-dlp && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Python deps from stage 1
COPY --from=deps /install /usr/local

# Application code
COPY . .

# Remove sensitive files that should NEVER be in the image
RUN rm -f credentials.json token.json service_account.json .env 2>/dev/null || true

# Copy initial DB and mind maps as seed data
RUN cp -r output/ /app/seed_output/ 2>/dev/null || true

# Create non-root user
RUN useradd -m -r appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8888

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8888/api/health || exit 1

CMD ["uvicorn", "dashboard:app", "--host", "0.0.0.0", "--port", "8888", "--proxy-headers", "--forwarded-allow-ips", "*"]
