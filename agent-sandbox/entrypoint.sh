#!/usr/bin/env bash
set -e

SANDBOX_DIR="${SANDBOX_DIR:-/ramdisk/sandbox}"
BIN_DIR="${SANDBOX_DIR}/bin"
VENV_DIR="${SANDBOX_DIR}/venv"
RUSTUP_HOME="${SANDBOX_DIR}/rustup"
CARGO_HOME="${SANDBOX_DIR}/cargo"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
JAVA_VERSION="${JAVA_VERSION:-21}"

echo "================================================================="
echo ">>> [Homelab Agent Sandbox] Initializing RAM Toolchains in ${SANDBOX_DIR}..."
echo "================================================================="

mkdir -p "${BIN_DIR}" "${SANDBOX_DIR}/runs" "${RUSTUP_HOME}" "${CARGO_HOME}"

# 1. Tectonic (LaTeX) Standalone Binary
if [ ! -f "${BIN_DIR}/tectonic" ]; then
    echo ">>> [Toolchain] Installing Tectonic standalone binary into RAM..."
    curl --proto '=https' --tlsv1.2 -fsSL https://drop-sh.fullyjustified.net | sh >/dev/null 2>&1 || true
    if [ -f "./tectonic" ]; then
        mv ./tectonic "${BIN_DIR}/tectonic"
        chmod +x "${BIN_DIR}/tectonic"
    fi
fi

# 2. Rust Toolchain (rustc / cargo in RAM)
export RUSTUP_HOME="${RUSTUP_HOME}"
export CARGO_HOME="${CARGO_HOME}"
export PATH="${BIN_DIR}:${CARGO_HOME}/bin:${PATH}"

if [ ! -f "${CARGO_HOME}/bin/rustc" ]; then
    echo ">>> [Toolchain] Installing Rust standalone toolchain into RAM..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path --profile minimal --default-toolchain stable >/dev/null 2>&1 || true
    if [ -f "${CARGO_HOME}/bin/rustc" ]; then
        ln -sf "${CARGO_HOME}/bin/rustc" "${BIN_DIR}/rustc"
        ln -sf "${CARGO_HOME}/bin/cargo" "${BIN_DIR}/cargo"
        ln -sf "${CARGO_HOME}/bin/rustup" "${BIN_DIR}/rustup"
    fi
else
    ln -sf "${CARGO_HOME}/bin/rustc" "${BIN_DIR}/rustc"
    ln -sf "${CARGO_HOME}/bin/cargo" "${BIN_DIR}/cargo"
fi

# 3. Dynamic Java Toolchain (JDK ${JAVA_VERSION} in RAM)
JDK_DIR="${SANDBOX_DIR}/jdk-${JAVA_VERSION}"
if [ -f "${JDK_DIR}/bin/javac" ]; then
    echo ">>> [Toolchain] Using cached Java JDK ${JAVA_VERSION} in RAM..."
    ln -sf "${JDK_DIR}/bin/javac" "${BIN_DIR}/javac"
    ln -sf "${JDK_DIR}/bin/java" "${BIN_DIR}/java"
    ln -sf "${JDK_DIR}/bin/jar" "${BIN_DIR}/jar"
else
    # Check if system java matches requested version
    SYS_JAVA_VER=$(javac --version 2>&1 | awk '{print $2}' | cut -d'.' -f1 || echo "")
    if [ "${SYS_JAVA_VER}" = "${JAVA_VERSION}" ] || [ -z "${JAVA_VERSION}" ]; then
        echo ">>> [Toolchain] Using system OpenJDK ${SYS_JAVA_VER}..."
        ln -sf "$(which javac)" "${BIN_DIR}/javac"
        ln -sf "$(which java)" "${BIN_DIR}/java"
    else
        echo ">>> [Toolchain] Downloading requested OpenJDK ${JAVA_VERSION} into RAM..."
        mkdir -p "${JDK_DIR}"
        # Fetch official Adoptium / Eclipse Temurin JDK tarball
        DOWNLOAD_URL="https://api.adoptium.net/v3/binary/latest/${JAVA_VERSION}/ga/linux/x64/jdk/hotspot/normal/eclipse"
        if curl -sL "${DOWNLOAD_URL}" | tar -xz -C "${JDK_DIR}" --strip-components=1 2>/dev/null; then
            echo ">>> [Toolchain] OpenJDK ${JAVA_VERSION} installed in RAM: ${JDK_DIR}"
            ln -sf "${JDK_DIR}/bin/javac" "${BIN_DIR}/javac"
            ln -sf "${JDK_DIR}/bin/java" "${BIN_DIR}/java"
            ln -sf "${JDK_DIR}/bin/jar" "${BIN_DIR}/jar"
        else
            echo ">>> [Toolchain] Fallback to system default Java..."
            ln -sf "$(which javac)" "${BIN_DIR}/javac"
            ln -sf "$(which java)" "${BIN_DIR}/java"
        fi
    fi
fi

# 4. C & C++ (GCC & G++ Standalone / System Links)
ln -sf "$(which gcc)" "${BIN_DIR}/gcc"
ln -sf "$(which g++)" "${BIN_DIR}/g++"
ln -sf "$(which make)" "${BIN_DIR}/make" 2>/dev/null || true

# 5. Fast Python Virtualenv with ML packages (uv / pip)
if [ ! -f "${VENV_DIR}/bin/python3" ]; then
    echo ">>> [Toolchain] Creating isolated Python ${PYTHON_VERSION} virtual environment in RAM..."
    python3 -m venv "${VENV_DIR}"
    "${VENV_DIR}/bin/pip" install --no-cache-dir --upgrade pip >/dev/null 2>&1 || true
    echo ">>> [Toolchain] Pre-installing essential agent libraries (numpy, pandas, scipy, matplotlib, sympy, pypdf, httpx, requests, flask)..."
    "${VENV_DIR}/bin/pip" install --no-cache-dir \
        numpy \
        pandas \
        scipy \
        matplotlib \
        sympy \
        pypdf \
        httpx \
        requests \
        flask \
        >/dev/null 2>&1 || true
fi

ln -sf "${VENV_DIR}/bin/python3" "${BIN_DIR}/python3"
ln -sf "${VENV_DIR}/bin/python" "${BIN_DIR}/python"
ln -sf "${VENV_DIR}/bin/pip" "${BIN_DIR}/pip"

echo ">>> [Homelab Agent Sandbox] All RAM toolchains verified and ready."
echo ">>> [Homelab Agent Sandbox] Launching Dual MCP Server (SSE Transport) & REST API on port 8088..."

export PATH="${BIN_DIR}:${VENV_DIR}/bin:${PATH}"
exec /usr/local/bin/python3 /app/server.py
