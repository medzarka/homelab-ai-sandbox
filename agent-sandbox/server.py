import os
import sys
import uuid
import time
import base64
import shutil
import asyncio
import re
import threading
import subprocess
from pathlib import Path
from typing import Dict, Optional, Any, List

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

# Try official MCP 2.0 MCPServer, fallback to FastMCP
try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer

# --- Configuration ---
SANDBOX_BASE = Path(os.environ.get("SANDBOX_DIR", "/ramdisk/sandbox"))
RUNS_DIR = SANDBOX_BASE / "runs"
BIN_DIR = SANDBOX_BASE / "bin"
VENV_DIR = SANDBOX_BASE / "venv"
SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL", 3600))
BASE_DOMAIN = os.environ.get("SANDBOX_DOMAIN", "sandbox.local")

# Ensure base directories exist
RUNS_DIR.mkdir(parents=True, exist_ok=True)
BIN_DIR.mkdir(parents=True, exist_ok=True)

# Global tracker for background servers: { session_id: {"process": proc, "port": int} }
ACTIVE_SERVERS: Dict[str, Dict[str, Any]] = {}

# --- Background Garbage Collector ---
def cleanup_stale_sessions():
    """Runs continuously in a background thread to purge expired sessions."""
    while True:
        try:
            time.sleep(300)  # Check every 5 minutes
            now = time.time()
            for d in RUNS_DIR.glob("session_*"):
                if d.is_dir():
                    try:
                        if now - d.stat().st_mtime > SESSION_TTL_SECONDS:
                            session_id = d.name.replace("session_", "")
                            if session_id in ACTIVE_SERVERS:
                                try:
                                    ACTIVE_SERVERS[session_id]["process"].kill()
                                except Exception:
                                    pass
                                del ACTIVE_SERVERS[session_id]
                            shutil.rmtree(d, ignore_errors=True)
                    except Exception:
                        pass
        except Exception:
            pass

gc_thread = threading.Thread(target=cleanup_stale_sessions, daemon=True)
gc_thread.start()

# --- Initialize FastMCP Server ---
mcp = MCPServer("Homelab-Execution-Sandbox")

# --- Utilities ---
def get_python_path(workdir: Optional[Path] = None) -> str:
    """Prioritizes session-specific virtualenv, falls back to global RAM venv or system python."""
    if workdir:
        session_py = workdir / ".venv" / "bin" / "python3"
        if session_py.exists():
            return str(session_py)
    global_py = VENV_DIR / "bin" / "python3"
    return str(global_py) if global_py.exists() else "/usr/local/bin/python3"

def get_binary(name: str) -> str:
    ram_bin = BIN_DIR / name
    return str(ram_bin) if ram_bin.exists() else (shutil.which(name) or name)

def process_file_writes(workdir: Path, code: str, entry_filename: str, files: Optional[Dict[str, str]] = None):
    """Safely handles file writing to RAM workdir with strict path traversal prevention."""
    workdir_resolved = workdir.resolve()

    if files:
        for fname, fcontent in files.items():
            target = (workdir / fname).resolve()
            if not target.is_relative_to(workdir_resolved):
                raise ValueError(f"Path traversal blocked for file: {fname}")

            target.parent.mkdir(parents=True, exist_ok=True)
            if fcontent.startswith("data:") and ";base64," in fcontent:
                raw_b64 = fcontent.split(";base64,")[1]
                target.write_bytes(base64.b64decode(raw_b64))
            else:
                target.write_text(fcontent, encoding="utf-8")

    entry_path = workdir / entry_filename
    entry_path.write_text(code, encoding="utf-8")

    try:
        workdir.touch()
    except Exception:
        pass

def collect_artifacts(workdir: Path, exclude_names: Optional[List[str]] = None) -> Dict[str, str]:
    """Collects generated output artifacts (PDFs, images, JSON, CSV)."""
    exclude = exclude_names or []
    artifacts = {}
    for f in workdir.glob("**/*"):
        if f.is_file() and f.name not in exclude and not f.name.startswith(".") and "site-packages" not in str(f):
            rel_name = str(f.relative_to(workdir))
            suffix = f.suffix.lower()
            if suffix == ".pdf":
                mime = "application/pdf"
            elif suffix == ".png":
                mime = "image/png"
            elif suffix in [".jpg", ".jpeg"]:
                mime = "image/jpeg"
            elif suffix == ".svg":
                mime = "image/svg+xml"
            else:
                try:
                    artifacts[rel_name] = f.read_text(encoding="utf-8")
                    continue
                except Exception:
                    mime = "application/octet-stream"

            b64 = base64.b64encode(f.read_bytes()).decode("utf-8")
            artifacts[rel_name] = f"data:{mime};base64,{b64}"
    return artifacts

# ==============================================================================
# MCP TOOLS (For Hermes Agent, Claude, Open-WebUI)
# ==============================================================================

@mcp.tool()
async def get_runtimes() -> str:
    """Check the availability and versions of supported compilers and runtimes in RAM."""
    info = []
    def check_cmd(cmd: list, name: str):
        try:
            out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT).splitlines()[0]
            info.append(f"- **{name}**: `{out.strip()}`")
        except Exception as e:
            info.append(f"- **{name}**: Not found ({str(e)})")

    check_cmd([get_python_path(), "--version"], "Python")
    check_cmd([get_binary("tectonic"), "--version"], "LaTeX (Tectonic)")
    check_cmd([get_binary("gcc"), "--version"], "C (GCC)")
    check_cmd([get_binary("g++"), "--version"], "C++ (G++)")
    check_cmd([get_binary("rustc"), "--version"], "Rust (rustc)")
    check_cmd([get_binary("javac"), "--version"], "Java (javac)")
    check_cmd([get_binary("java"), "--version"], "Java Runtime")

    return "### Available In-Memory Runtimes\n" + "\n".join(info)

@mcp.tool()
async def execute_code(
    language: str,
    code: str,
    files: Optional[Dict[str, str]] = None,
    timeout: int = 60,
    session_id: Optional[str] = None
) -> str:
    """
    Executes code in a secure in-memory sandbox. Use session_id to maintain state across runs.
    
    Args:
        language: "python", "latex", "c", "cpp", "rust", "java", or "sh"
        code: The main source code to execute.
        files: Optional dictionary of {filename: content} for multi-file projects.
        timeout: Execution timeout in seconds (max 300).
        session_id: Optional ID to persist files across multiple executions.
    """
    lang = language.lower().strip()
    timeout = min(max(timeout, 1), 300)

    is_ephemeral = not session_id
    if is_ephemeral:
        current_run_id = f"run_{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}"
        workdir = RUNS_DIR / current_run_id
    else:
        safe_session = re.sub(r'[^a-zA-Z0-9_-]', '', session_id)
        if not safe_session:
            return "Error: Invalid session_id format. Use alphanumeric and dashes."
        current_run_id = safe_session
        workdir = RUNS_DIR / f"session_{safe_session}"

    workdir.mkdir(parents=True, exist_ok=True)

    try:
        env = os.environ.copy()
        env["PATH"] = f"{BIN_DIR}:{VENV_DIR}/bin:{env.get('PATH', '')}"
        env["RUSTUP_TOOLCHAIN"] = "stable"
        env["RUSTUP_HOME"] = str(SANDBOX_BASE / "rustup")
        env["CARGO_HOME"] = str(SANDBOX_BASE / "cargo")

        if lang in ["python", "py"]:
            entry_file = "script.py"
            cmd = [get_python_path(workdir), "script.py"]
        elif lang in ["latex", "tex", "tectonic"]:
            entry_file = "document.tex"
            cmd = [get_binary("tectonic"), "-o", str(workdir), "document.tex"]
        elif lang in ["c"]:
            entry_file = "main.c"
            compile_cmd = f"{get_binary('gcc')} -O2 *.c -o main -lm && ./main"
            cmd = ["/bin/sh", "-c", compile_cmd]
        elif lang in ["cpp", "c++"]:
            entry_file = "main.cpp"
            compile_cmd = f"{get_binary('g++')} -O2 -std=c++20 *.cpp -o main -lm && ./main"
            cmd = ["/bin/sh", "-c", compile_cmd]
        elif lang in ["rust", "rs"]:
            entry_file = "main.rs"
            compile_cmd = f"{get_binary('rustc')} -O main.rs -o main && ./main"
            cmd = ["/bin/sh", "-c", compile_cmd]
        elif lang in ["java"]:
            entry_file = "Main.java"
            compile_cmd = f"{get_binary('javac')} *.java && {get_binary('java')} Main"
            cmd = ["/bin/sh", "-c", compile_cmd]
        elif lang in ["sh", "bash", "shell"]:
            entry_file = "script.sh"
            cmd = ["/bin/bash", "script.sh"]
        else:
            return f"Error: Unsupported language '{lang}'. Supported: python, latex, c, cpp, rust, java, sh"

        try:
            await asyncio.to_thread(process_file_writes, workdir, code, entry_file, files)
        except ValueError as e:
            return f"Security Error: {str(e)}"

        if lang in ["sh", "bash", "shell"]:
            (workdir / entry_file).chmod(0o755)

        t0 = time.time()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(workdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )

        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            exit_code = proc.returncode
        except asyncio.TimeoutError:
            proc.kill()
            stdout_b, stderr_b = b"", f"Execution timed out after {timeout} seconds".encode()
            exit_code = -1

        duration_ms = (time.time() - t0) * 1000
        raw_artifacts = await asyncio.to_thread(collect_artifacts, workdir, [entry_file, "main"])

        response = [
            f"### Execution Complete ({duration_ms:.0f}ms)",
            f"**Exit Code:** `{exit_code}`",
            f"**Session ID:** `{current_run_id}`" if not is_ephemeral else "**Run:** Ephemeral (Not saved)"
        ]

        if stdout_b:
            response.append(f"\n**Stdout:**\n```text\n{stdout_b.decode('utf-8', errors='replace').strip()}\n```")
        if stderr_b:
            response.append(f"\n**Stderr:**\n```text\n{stderr_b.decode('utf-8', errors='replace').strip()}\n```")

        if raw_artifacts:
            response.append("\n**Generated Artifacts:**")
            for art_name in raw_artifacts.keys():
                if not is_ephemeral:
                    response.append(f"- `{art_name}` (Read via Resource URI: `sandbox://{current_run_id}/{art_name}`)")
                else:
                    response.append(f"- `{art_name}`")

        return "\n".join(response)
    finally:
        if is_ephemeral:
            await asyncio.to_thread(shutil.rmtree, workdir, ignore_errors=True)

@mcp.tool()
async def run_command(session_id: str, command: str, timeout: int = 120) -> str:
    """
    Runs an arbitrary shell command in an active session directory (e.g., pip install, venv creation).
    """
    safe_session = re.sub(r'[^a-zA-Z0-9_-]', '', session_id)
    workdir = RUNS_DIR / f"session_{safe_session}"

    if not workdir.exists():
        return f"Error: Session `{safe_session}` not found."

    env = os.environ.copy()
    env["PATH"] = f"{BIN_DIR}:{VENV_DIR}/bin:{env.get('PATH', '')}"

    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=str(workdir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env
    )

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        out = stdout_b.decode('utf-8', errors='replace').strip()
        err = stderr_b.decode('utf-8', errors='replace').strip()
        return f"Exit Code: {proc.returncode}\nStdout:\n{out}\nStderr:\n{err}"
    except asyncio.TimeoutError:
        proc.kill()
        return "Error: Command timed out after 120 seconds."

@mcp.tool()
async def start_web_server(session_id: str, command: str, port: int) -> str:
    """
    Starts a long-running background web server (like Flask or FastAPI) inside the session workspace.
    """
    safe_session = re.sub(r'[^a-zA-Z0-9_-]', '', session_id)
    workdir = RUNS_DIR / f"session_{safe_session}"

    if not workdir.exists():
        return f"Error: Session `{safe_session}` not found."

    if safe_session in ACTIVE_SERVERS:
        try:
            ACTIVE_SERVERS[safe_session]["process"].kill()
        except Exception:
            pass
        del ACTIVE_SERVERS[safe_session]

    env = os.environ.copy()
    env["PATH"] = f"{BIN_DIR}:{VENV_DIR}/bin:{env.get('PATH', '')}"
    env["PYTHONUNBUFFERED"] = "1"

    log_file = open(workdir / "server.log", "w")
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=str(workdir),
        stdout=log_file,
        stderr=log_file,
        env=env
    )

    ACTIVE_SERVERS[safe_session] = {"process": proc, "port": port, "log_file": log_file}
    return f"🟢 Background server started on port {port} for session `{safe_session}` (PID {proc.pid})."

@mcp.tool()
async def stop_web_server(session_id: str) -> str:
    """Stops the background web server for a given active session."""
    safe_session = re.sub(r'[^a-zA-Z0-9_-]', '', session_id)

    if safe_session in ACTIVE_SERVERS:
        try:
            ACTIVE_SERVERS[safe_session]["process"].kill()
        except Exception:
            pass
        del ACTIVE_SERVERS[safe_session]
        return f"Server for session `{safe_session}` has been stopped."
    return f"No active server found for session `{safe_session}`."

@mcp.tool()
async def delete_file(session_id: str, filename: str) -> str:
    """Deletes a specific file or directory from an active session workspace."""
    safe_session = re.sub(r'[^a-zA-Z0-9_-]', '', session_id)
    workdir = RUNS_DIR / f"session_{safe_session}"

    if not workdir.exists():
        return f"Error: Session `{safe_session}` not found."

    target = (workdir / filename).resolve()
    if not target.is_relative_to(workdir.resolve()):
        return f"Security Error: Path traversal blocked for `{filename}`."

    if target == workdir.resolve():
        return "Error: Cannot delete the session root. Use close_session instead."

    if not target.exists():
        return f"Error: Path `{filename}` does not exist in session `{safe_session}`."

    def _do_delete():
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()

    try:
        await asyncio.to_thread(_do_delete)
        return f"Successfully deleted `{filename}` from session `{safe_session}`."
    except Exception as e:
        return f"Error deleting `{filename}`: {str(e)}"

@mcp.tool()
async def close_session(session_id: str) -> str:
    """Manually closes and purges an active session and all its files from RAM."""
    safe_session = re.sub(r'[^a-zA-Z0-9_-]', '', session_id)
    workdir = RUNS_DIR / f"session_{safe_session}"

    if safe_session in ACTIVE_SERVERS:
        try:
            ACTIVE_SERVERS[safe_session]["process"].kill()
        except Exception:
            pass
        del ACTIVE_SERVERS[safe_session]

    if workdir.exists():
        await asyncio.to_thread(shutil.rmtree, workdir, ignore_errors=True)
        return f"Session `{safe_session}` closed and purged from RAM."
    return f"Session `{safe_session}` not found."

# ==============================================================================
# MCP RESOURCES
# ==============================================================================

@mcp.resource("sandbox://{session_id}/{filename}")
def read_sandbox_file(session_id: str, filename: str) -> str | bytes:
    """Read the contents of a generated file from an active session."""
    safe_session = re.sub(r'[^a-zA-Z0-9_-]', '', session_id)
    workdir = RUNS_DIR / f"session_{safe_session}"

    if not workdir.exists():
        raise ValueError(f"Session '{safe_session}' not found.")

    target = (workdir / filename).resolve()
    if not target.is_relative_to(workdir.resolve()):
        raise ValueError("Path traversal blocked.")

    if not target.exists() or not target.is_file():
        raise ValueError(f"File '{filename}' not found.")

    ext = target.suffix.lower()
    if ext in [".pdf", ".png", ".jpg", ".jpeg", ".zip", ".tar", ".gz"]:
        return target.read_bytes()

    return target.read_text(encoding="utf-8", errors="replace")

# ==============================================================================
# FASTAPI DUAL INTERFACE (REST Endpoints + MCP SSE Routes)
# ==============================================================================

app = FastAPI(title="Homelab Agent Execution Sandbox & MCP Server", version="2.0.0")


class ExecuteRequest(BaseModel):
    language: str
    code: str
    files: Optional[Dict[str, str]] = None
    timeout: Optional[int] = 60
    session_id: Optional[str] = None

class ExecuteResponse(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    session_id: Optional[str] = None
    artifacts: Dict[str, str] = {}

class CommandRequest(BaseModel):
    session_id: str
    command: str
    timeout: Optional[int] = 120

class ServerRequest(BaseModel):
    session_id: str
    command: str
    port: int

class StopServerRequest(BaseModel):
    session_id: str

class SessionRequest(BaseModel):
    session_id: str

# --- API Key Authentication Guard ---
SANDBOX_API_KEY = os.environ.get("SANDBOX_API_KEY") or None

@app.middleware("http")
async def api_key_auth_middleware(request: Request, call_next):
    if SANDBOX_API_KEY and request.url.path not in ["/health", "/docs", "/openapi.json"]:
        auth_header = request.headers.get("Authorization", "")
        api_key_header = request.headers.get("X-API-Key", "")
        token = auth_header.replace("Bearer ", "").strip() if "Bearer " in auth_header else api_key_header
        if token != SANDBOX_API_KEY:
            return JSONResponse(status_code=401, content={"error": "Unauthorized: Invalid or missing API key."})
    return await call_next(request)

@app.get("/health")
def health():
    return {
        "status": "ok",
        "sandbox_dir": str(SANDBOX_BASE),
        "active_sessions": [d.name.replace("session_", "") for d in RUNS_DIR.glob("session_*") if d.is_dir()],
        "active_servers": list(ACTIVE_SERVERS.keys()),
        "mcp_sse_endpoint": "/sse"
    }

@app.get("/runtimes")
async def runtimes_endpoint():
    res = await get_runtimes()
    return {"runtimes_markdown": res}

@app.post("/execute", response_model=ExecuteResponse)
async def rest_execute(req: ExecuteRequest):
    lang = req.language.lower().strip()
    timeout = min(max(req.timeout or 60, 1), 300)

    is_ephemeral = not req.session_id
    if is_ephemeral:
        current_run_id = f"run_{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}"
        workdir = RUNS_DIR / current_run_id
    else:
        safe_session = re.sub(r'[^a-zA-Z0-9_-]', '', req.session_id)
        if not safe_session:
            raise HTTPException(status_code=400, detail="Invalid session_id format.")
        current_run_id = safe_session
        workdir = RUNS_DIR / f"session_{safe_session}"

    workdir.mkdir(parents=True, exist_ok=True)

    try:
        env = os.environ.copy()
        env["PATH"] = f"{BIN_DIR}:{VENV_DIR}/bin:{env.get('PATH', '')}"
        env["RUSTUP_TOOLCHAIN"] = "stable"
        env["RUSTUP_HOME"] = str(SANDBOX_BASE / "rustup")
        env["CARGO_HOME"] = str(SANDBOX_BASE / "cargo")

        if lang in ["python", "py"]:
            entry_file = "script.py"
            cmd = [get_python_path(workdir), "script.py"]
        elif lang in ["latex", "tex", "tectonic"]:
            entry_file = "document.tex"
            cmd = [get_binary("tectonic"), "-o", str(workdir), "document.tex"]
        elif lang in ["c"]:
            entry_file = "main.c"
            compile_cmd = f"{get_binary('gcc')} -O2 *.c -o main -lm && ./main"
            cmd = ["/bin/sh", "-c", compile_cmd]
        elif lang in ["cpp", "c++"]:
            entry_file = "main.cpp"
            compile_cmd = f"{get_binary('g++')} -O2 -std=c++20 *.cpp -o main -lm && ./main"
            cmd = ["/bin/sh", "-c", compile_cmd]
        elif lang in ["rust", "rs"]:
            entry_file = "main.rs"
            compile_cmd = f"{get_binary('rustc')} -O main.rs -o main && ./main"
            cmd = ["/bin/sh", "-c", compile_cmd]
        elif lang in ["java"]:
            entry_file = "Main.java"
            compile_cmd = f"{get_binary('javac')} *.java && {get_binary('java')} Main"
            cmd = ["/bin/sh", "-c", compile_cmd]
        elif lang in ["sh", "bash", "shell"]:
            entry_file = "script.sh"
            cmd = ["/bin/bash", "script.sh"]
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported language: {lang}")

        try:
            await asyncio.to_thread(process_file_writes, workdir, req.code, entry_file, req.files)
        except ValueError as e:
            raise HTTPException(status_code=403, detail=str(e))

        if lang in ["sh", "bash", "shell"]:
            (workdir / entry_file).chmod(0o755)

        t0 = time.time()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(workdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )

        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            exit_code = proc.returncode
        except asyncio.TimeoutError:
            proc.kill()
            stdout_b, stderr_b = b"", f"Execution timed out after {timeout} seconds".encode()
            exit_code = -1

        duration_ms = (time.time() - t0) * 1000
        artifacts = await asyncio.to_thread(collect_artifacts, workdir, [entry_file, "main"])

        return ExecuteResponse(
            exit_code=exit_code,
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
            duration_ms=round(duration_ms, 2),
            session_id=req.session_id,
            artifacts=artifacts
        )
    finally:
        if is_ephemeral:
            await asyncio.to_thread(shutil.rmtree, workdir, ignore_errors=True)

@app.post("/run-command")
async def rest_run_command(req: CommandRequest):
    res = await run_command(req.session_id, req.command, req.timeout or 120)
    return {"result": res}

@app.post("/start-server")
async def rest_start_server(req: ServerRequest):
    res = await start_web_server(req.session_id, req.command, req.port)
    return {"result": res}

@app.post("/stop-server")
async def rest_stop_server(req: StopServerRequest):
    res = await stop_web_server(req.session_id)
    return {"result": res}

@app.delete("/sessions/{session_id}")
async def rest_close_session(session_id: str):
    res = await close_session(session_id)
    return {"result": res}

# Mount MCP SSE application for Hermes & Open-WebUI with relaxed host protection for LAN/Tailscale
try:
    from mcp.server.transport_security import TransportSecuritySettings
    ts_settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
        allowed_hosts=["*"],
        allowed_origins=["*"]
    )
    sse_app = mcp.sse_app(transport_security=ts_settings)
    app.mount("/mcp", sse_app)
    
    @app.get("/sse")
    async def sse_root(request: Request):
        return await sse_app(request.scope, request.receive, request._send)
except Exception as e:
    print("Notice: Mounting custom SSE route:", e)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8088)
