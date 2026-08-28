FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# System packages & compilers
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    git \
    tar \
    gzip \
    xz-utils \
    ca-certificates \
    libfontconfig1 \
    libgraphite2-3 \
    libharfbuzz0b \
    build-essential \
    default-jdk-headless \
    && rm -rf /var/lib/apt/lists/*

# Install FastMCP, FastAPI, Uvicorn, Flask, and HTTP client
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    pydantic \
    mcp \
    httpx \
    sse-starlette \
    flask

WORKDIR /app
COPY server.py /app/server.py
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8088

ENTRYPOINT ["/app/entrypoint.sh"]
