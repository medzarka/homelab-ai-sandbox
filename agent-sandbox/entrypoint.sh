#!/usr/bin/env bash
set -e

SANDBOX_DIR="${SANDBOX_DIR:-/ramdisk/sandbox}"
BIN_DIR="${SANDBOX_DIR}/bin"
VENV_DIR="${SANDBOX_DIR}/venv"
RUSTUP_HOME="${RUSTUP_HOME:-/opt/rust/rustup}"
CARGO_HOME="${CARGO_HOME:-/opt/rust/cargo}"

echo "================================================================="
echo ">>> [Homelab Agent Sandbox] Instant Toolchain Initialization..."
echo "================================================================="

mkdir -p "${BIN_DIR}" "${SANDBOX_DIR}/runs"

# 1. Tectonic (LaTeX) Pre-Baked Binary
if [ -x "/usr/local/bin/tectonic" ]; then
    ln -sf "/usr/local/bin/tectonic" "${BIN_DIR}/tectonic"
elif [ -f "${BIN_DIR}/tectonic" ]; then
    chmod +x "${BIN_DIR}/tectonic"
fi

# 2. Rust Toolchain (Pre-Baked in /opt/rust)
export RUSTUP_HOME="${RUSTUP_HOME}"
export CARGO_HOME="${CARGO_HOME}"

if [ -x "/opt/rust/cargo/bin/rustc" ]; then
    ln -sf "/opt/rust/cargo/bin/rustc" "${BIN_DIR}/rustc"
    ln -sf "/opt/rust/cargo/bin/cargo" "${BIN_DIR}/cargo"
fi

# 3. Java Toolchain (Pre-Baked OpenJDK)
if command -v javac >/dev/null 2>&1; then
    ln -sf "$(command -v javac)" "${BIN_DIR}/javac"
    ln -sf "$(command -v java)" "${BIN_DIR}/java"
    ln -sf "$(command -v jar)" "${BIN_DIR}/jar" 2>/dev/null || true
fi

# 4. C & C++ (GCC & G++ Standalone / System Links)
if command -v gcc >/dev/null 2>&1; then
    ln -sf "$(command -v gcc)" "${BIN_DIR}/gcc"
fi
if command -v g++ >/dev/null 2>&1; then
    ln -sf "$(command -v g++)" "${BIN_DIR}/g++"
fi
if command -v make >/dev/null 2>&1; then
    ln -sf "$(command -v make)" "${BIN_DIR}/make"
fi

# 5. Shell & DevOps Core Utilities
for cmd in bash sh git curl wget jq unzip zip tar gzip rsync tree; do
    if command -v "$cmd" >/dev/null 2>&1; then
        ln -sf "$(command -v "$cmd")" "${BIN_DIR}/$cmd"
    fi
done

# 6. Pre-Baked Python Environment & ML Libraries (/opt/venv)
if [ -d "/opt/venv" ]; then
    ln -sf "/opt/venv/bin/python3" "${BIN_DIR}/python3"
    ln -sf "/opt/venv/bin/python" "${BIN_DIR}/python"
    ln -sf "/opt/venv/bin/pip" "${BIN_DIR}/pip"
    ln -sf "/opt/venv/bin/python3" "/usr/local/bin/python3" 2>/dev/null || true
    ln -sf "/opt/venv/bin/pip" "/usr/local/bin/pip" 2>/dev/null || true
fi

export PATH="${BIN_DIR}:/opt/venv/bin:/opt/rust/cargo/bin:/usr/local/bin:${PATH}"

echo ">>> [Homelab Agent Sandbox] All toolchains linked in < 0.1s (Zero-Download Startup)."
echo ">>> [Homelab Agent Sandbox] Available tools: Bash, Python, Java, Rust, C, C++, LaTeX, Git, Curl, Wget, Jq"
echo ">>> [Homelab Agent Sandbox] Launching Dual MCP Server (SSE Transport) & REST API on port 8088..."

exec /opt/venv/bin/python3 /app/server.py
