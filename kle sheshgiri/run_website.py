#!/usr/bin/env python3
"""Launch the MediShield backend and frontend on free local ports."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend" / "asteria frontend"


def _find_free_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]


def _wait_for(url: str, timeout_seconds: int = 20) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # pragma: no cover - startup probing
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def main() -> int:
    backend_port = _find_free_port(8000)
    frontend_port = _find_free_port(8080 if backend_port != 8080 else 8081)

    backend_env = os.environ.copy()
    backend_env["PYTHONUNBUFFERED"] = "1"

    backend_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(backend_port),
    ]
    frontend_cmd = [
        sys.executable,
        "-m",
        "http.server",
        str(frontend_port),
        "--bind",
        "127.0.0.1",
    ]

    backend_proc = subprocess.Popen(backend_cmd, cwd=BACKEND_DIR, env=backend_env)
    frontend_proc = subprocess.Popen(frontend_cmd, cwd=FRONTEND_DIR, env=backend_env)

    backend_url = f"http://127.0.0.1:{backend_port}"
    frontend_url = f"http://127.0.0.1:{frontend_port}/asteria%20frontend.html?api={backend_url}"

    try:
        _wait_for(f"{backend_url}/health")
        _wait_for(frontend_url)
        print("MediShield website is running.")
        print(f"Backend:  {backend_url}")
        print(f"Frontend: {frontend_url}")
        print("Press Ctrl+C to stop both servers.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping servers...")
    finally:
        for proc in (backend_proc, frontend_proc):
            if proc.poll() is None:
                proc.terminate()
        for proc in (backend_proc, frontend_proc):
            try:
                proc.wait(timeout=5)
            except Exception:
                if proc.poll() is None:
                    proc.kill()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
