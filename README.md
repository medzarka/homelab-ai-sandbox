# Homelab AI Sandbox

This repository contains the **Agent Execution Sandbox**, a highly secure, headless code-execution environment designed specifically for AI agents (like Hermes or Claude). 

It exposes a robust **Model Context Protocol (MCP)** server over both REST and SSE, allowing AI agents to securely write, compile, and execute code within an ephemeral, strictly controlled environment.

## Features
- **Multi-Language Support**: Compiles and runs Python, C, C++, Rust, Java, and Bash.
- **Tectonic LaTeX Engine**: Compiles academic and complex math PDFs on the fly.
- **RAM-Disk Isolation**: All code execution, scratch files, and binaries live entirely on a host-provided ephemeral RAM disk (`/mnt/ramdisk`). Everything is wiped from memory once the session TTL expires.
- **API Key Security**: Endpoints are strictly protected by API key authentication.
- **Traefik Ingress**: Connect securely over the internet via Traefik or directly over the internal Docker Swarm network.

## Getting Started

1. **Clone the repository.**
2. **Configure Environment:**
   Copy `.env.example` to `.env` and generate a strong security key:
   ```bash
   cp .env.example .env
   openssl rand -hex 32
   # Add the generated key to SANDBOX_API_KEY in .env
   ```
3. **Deploy:**
   If using Arcane (or standard Docker Swarm):
   ```bash
   docker compose up -d
   ```

## Connecting an Agent

To connect an MCP-compatible client, configure it to hit the SSE endpoint with your API key.

**Example for Claude Desktop / Hermes:**
```json
{
  "mcpServers": {
    "homelab-sandbox": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/client-sse", "--url", "https://sandbox.yourdomain.com/mcp/sse"],
      "env": {
        "X-API-Key": "sk-your-secure-sandbox-key"
      }
    }
  }
}
```

## CI/CD
This repository includes a GitHub Action to automatically build and publish the `agent-sandbox` multi-architecture Docker image (AMD64 & ARM64) to GHCR on every push to `main`.
