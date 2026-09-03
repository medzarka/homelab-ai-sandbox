FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV RUSTUP_HOME=/opt/rust/rustup
ENV CARGO_HOME=/opt/rust/cargo
ENV PATH=/opt/rust/cargo/bin:/opt/venv/bin:/usr/local/bin:$PATH

# 1. System packages, compilers, and common DevOps utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    curl \
    wget \
    git \
    jq \
    unzip \
    zip \
    rsync \
    tar \
    gzip \
    xz-utils \
    bzip2 \
    ca-certificates \
    procps \
    tree \
    iproute2 \
    dnsutils \
    netcat-openbsd \
    socat \
    file \
    bc \
    sed \
    gawk \
    patch \
    build-essential \
    pkg-config \
    default-jdk-headless \
    libfontconfig1 \
    libgraphite2-3 \
    libharfbuzz0b \
    && rm -rf /var/lib/apt/lists/*

# 2. Pre-install Tectonic (LaTeX engine) static binary based on architecture
RUN ARCH="$(uname -m)" && \
    case "${ARCH}" in \
        x86_64|amd64) TECTONIC_ARCH="x86_64-unknown-linux-musl" ;; \
        aarch64|arm64) TECTONIC_ARCH="aarch64-unknown-linux-musl" ;; \
        *) TECTONIC_ARCH="x86_64-unknown-linux-musl" ;; \
    esac && \
    curl -sL "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.17.0/tectonic-0.17.0-${TECTONIC_ARCH}.tar.gz" | tar -xz -C /usr/local/bin && \
    chmod +x /usr/local/bin/tectonic && \
    tectonic --version

# 3. Pre-install Rust toolchain (rustc / cargo)
RUN mkdir -p /opt/rust && \
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path --profile minimal --default-toolchain stable && \
    ln -sf /opt/rust/cargo/bin/rustc /usr/local/bin/rustc && \
    ln -sf /opt/rust/cargo/bin/cargo /usr/local/bin/cargo && \
    rustc --version && cargo --version

# 4. Pre-bake isolated Python virtual environment with essential ML, agent, and server libraries
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir \
        fastapi \
        "uvicorn[standard]" \
        pydantic \
        mcp \
        httpx \
        sse-starlette \
        flask \
        numpy \
        pandas \
        scipy \
        matplotlib \
        sympy \
        pypdf \
        requests && \
    pip install --no-cache-dir \
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
