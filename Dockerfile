# syntax=docker/dockerfile:1
# Base Image: Python 3.12 Debian Bookworm (ARM64 & x86_64 compatible)
FROM docker.io/library/python:3.12-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PATH="/app/.venv/bin:/usr/local/bin:$PATH"

# Install System Dependencies: Chromium & Chromedriver
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    gnupg \
    chromium \
    chromium-driver \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv for Python dependency management into /usr/local/bin (accessible by non-root users)
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="/usr/local/bin" sh

# Set Working Directory
WORKDIR /app

# 1. Copy package management files first (for Docker layer caching)
COPY pyproject.toml uv.lock* ./

# 2. Install dependencies using system python3 and grant read/execute permissions for rootless container
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --python /usr/local/bin/python3 && \
    chmod -R a+rX /app/.venv

# 3. Install Playwright browser dependencies (uses host cache to skip downloading if already cached)
RUN --mount=type=cache,target=/var/cache/playwright \
    PLAYWRIGHT_BROWSERS_PATH=/var/cache/playwright uv run playwright install chromium && \
    mkdir -p /ms-playwright && \
    cp -rp /var/cache/playwright/. /ms-playwright/ && \
    chmod -R a+rX /ms-playwright

# 4. Copy the rest of the application source code
COPY . .

# Expose Port 8000 for Backend FastAPI
EXPOSE 8000

# Default Command: Run FastAPI Backend using virtualenv uvicorn directly
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
