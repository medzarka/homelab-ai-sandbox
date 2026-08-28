# Homelab Agent Execution Sandbox & MCP Server

An ultra-high-speed, in-memory **Model Context Protocol (MCP)** server and **REST Execution API** tailored for autonomous AI coding agents (such as **Hermes Agent**, **Open-WebUI**, **Claude Desktop**, and custom Python agents).

Operating exclusively inside a dedicated RAM-disk (`/mnt/ramdisk/sandbox`), the sandbox eliminates physical disk I/O latency and flash wear while delivering sub-second compilation and execution across **Python 3.12**, **LaTeX (Tectonic PDF)**, **C (GCC)**, **C++20 (G++)**, **Rust (`rustc`)**, and **Java (OpenJDK)**.

---

## 🌟 Key Features

1. **Native Model Context Protocol (MCP) Support**:
   - Implements the official Python **FastMCP** framework with **Server-Sent Events (SSE)** transport on port `8088` (`/sse` and `/messages/`).
   - Seamless zero-code integration with **Hermes Agent** and **Open-WebUI**.
2. **Stateful Sessions & Incremental File Caching**:
   - Supports long-lived session workspaces via `session_id`.
   - Upload a 50-file repository once; subsequent tool calls only need to transmit the specific file(s) modified.
3. **Background Web Server Management (Flask / FastAPI / Node)**:
   - Built-in `start_web_server` and `stop_web_server` tools enable agents to spawn long-running web servers on dynamic ports without hanging execution timeouts.
4. **Isolated Virtual Environments**:
   - Each session can build its own isolated `.venv` via `run_command` (`pip install -r requirements.txt`). The sandbox automatically prioritizes session-specific virtual environments.
5. **Dynamic Runtimes via `.env`**:
   - **`JAVA_VERSION`**: Configurable in `.env` (`JAVA_VERSION=21`, `17`, `11`). Automatically downloads and links the requested JDK version in RAM without rebuilding the Docker container.
   - **`PYTHON_VERSION`**: Pre-configured Python 3.12 ML environment (NumPy, SciPy, Pandas, Matplotlib, SymPy, PyPDF, Requests, Flask).
6. **Hardened Security & Resource Isolation**:
   - Strict path traversal prevention (`is_relative_to` validation).
   - Regex-sanitized session identifiers (`^[a-zA-Z0-9_-]+$`).
   - Automatic background TTL garbage collector purging inactive sessions older than `SESSION_TTL` (default: 1 hour).

---

## 🛠️ MCP Tool Definitions

When Hermes Agent or Open-WebUI connects to `http://100.x.y.z:8088/sse`, the following tools are automatically registered:

### 1. `execute_code`
Executes source code in the sandbox.
```json
{
  "language": "python | latex | c | cpp | rust | java | sh",
  "code": "string (main entrypoint source code)",
  "files": { "helper.py": "content", "data.csv": "col1,col2..." },
  "timeout": 60,
  "session_id": "optional_session_identifier"
}
```

### 2. `run_command`
Runs an arbitrary shell command inside an active session directory (e.g. `pip install`, `ls -la`, `cargo build`).
```json
{
  "session_id": "proj_123",
  "command": "pip install -r requirements.txt",
  "timeout": 120
}
```

### 3. `start_web_server`
Launches a long-running background web server (must bind to `0.0.0.0`).
```json
{
  "session_id": "my_flask_app",
  "command": "python3 app.py",
  "port": 5000
}
```

### 4. `stop_web_server`
Terminates the active background server for a given session.
```json
{
  "session_id": "my_flask_app"
}
```

### 5. `delete_file`
Safely removes a specific file or directory from an active session.
```json
{
  "session_id": "proj_123",
  "filename": "old_config.json"
}
```

### 6. `close_session`
Manually closes the session, terminates background processes, and purges all files from RAM.
```json
{
  "session_id": "proj_123"
}
```

### 7. `get_runtimes`
Returns markdown-formatted versions of all available compilers and runtimes.

---

## 📦 MCP Resources

Generated output files (e.g., compiled PDFs, generated charts, exported CSVs) are accessible as MCP resources:
```text
sandbox://{session_id}/{filename}
```
*Example*: `sandbox://math_paper/document.pdf`

---

## 🤖 Configuring Hermes Agent

Hermes Agent has native support for remote HTTP/SSE MCP servers.

### Step 1: Edit Hermes Configuration
Open `~/.hermes/config.yaml` (or the corresponding Hermes environment config) and add the sandbox under `mcp_servers`:

```yaml
mcp_servers:
  homelab_sandbox:
    url: "http://100.x.y.z:8088/sse"
```

### Step 2: Start Hermes Chat
```bash
hermes chat
```
Hermes will establish an SSE handshake with `http://100.x.y.z:8088/sse`, discover all 7 tools, and make them available for code execution, compilation, and file manipulation.

---

## 🌐 Configuring Open-WebUI

1. Open **Open-WebUI** → **Admin Panel** → **Settings** → **MCP Servers**.
2. Click **Add Server**:
   - **Name**: `Homelab Sandbox`
   - **Transport Type**: `SSE`
   - **SSE URL**: `http://100.x.y.z:8088/sse`
3. Save and toggle the server ON for your models.

---

## 🐍 Python Client Example (`mcp` SDK)

```python
import asyncio
from mcp import ClientSession
from mcp.client.sse import sse_client

async def run():
    server_url = "http://100.x.y.z:8088/sse"
    async with sse_client(server_url) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            
            # List available tools
            tools = await session.list_tools()
            print("Tools:", [t.name for t in tools.tools])
            
            # Execute code
            res = await session.call_tool(
                "execute_code",
                arguments={
                    "language": "python",
                    "code": "import numpy as np; print(np.mean([10, 20, 30]))"
                }
            )
            print(res.content[0].text)

asyncio.run(run())
```

---

## 🌐 Dual REST HTTP Endpoints

For direct programmatic access without MCP:

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/health` | `GET` | Health status and active sessions list |
| `/runtimes` | `GET` | Compiler versions in Markdown |
| `/execute` | `POST` | Execute code with JSON payload |
| `/run-command` | `POST` | Execute shell command in session |
| `/start-server` | `POST` | Start background web server |
| `/stop-server` | `POST` | Stop background web server |
| `/sessions/{id}` | `DELETE` | Close and purge session |
| `/sse` | `GET` | MCP SSE handshake endpoint |
| `/messages/` | `POST` | MCP JSON-RPC message handler |
