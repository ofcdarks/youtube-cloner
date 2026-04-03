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
LABEL version="3.3"

WORKDIR /app

# System deps + Playwright browser deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl ca-certificates \
    # Playwright Chromium deps
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 libxshmfence1 \
    && curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp \
    && chmod a+rx /usr/local/bin/yt-dlp \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Python deps from stage 1
COPY --from=deps /install /usr/local

# Playwright browsers go to a shared path (not user-specific)
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Install Playwright Chromium browser
RUN python -m playwright install --with-deps chromium && \
    chmod -R 755 /ms-playwright

# Application code
COPY . .

# Remove sensitive files
RUN rm -f credentials.json token.json service_account.json .env 2>/dev/null || true

# Seed data
RUN cp -r output/ /app/seed_output/ 2>/dev/null || true

# Create non-root user with home dir for Playwright storage
RUN useradd -m -r appuser && \
    chown -R appuser:appuser /app && \
    mkdir -p /app/output && chown -R appuser:appuser /app/output && \
    mkdir -p /home/appuser/.notebooklm && chown -R appuser:appuser /home/appuser
USER appuser

EXPOSE 8888

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8888/api/health || exit 1

CMD ["uvicorn", "dashboard:app", "--host", "0.0.0.0", "--port", "8888", "--proxy-headers", "--forwarded-allow-ips", "*"]
