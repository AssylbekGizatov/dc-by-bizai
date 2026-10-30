#!/usr/bin/env python3
"""Run the local-only API and Vite; stop both process groups on exit."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    children: list[subprocess.Popen[bytes]] = []
    frontend_args = sys.argv[1:]
    has_port = any(value == "--port" or value.startswith("--port=") for value in frontend_args)
    if not has_port:
        frontend_args += ["--port", os.getenv("FRONTEND_PORT") or os.getenv("PORT") or "5173"]

    def stop(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        for command, cwd in (
            ([sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", "backend",
              "--host", "127.0.0.1", "--port", "8000", "--reload", "--reload-dir", "backend/app", "--no-access-log"], ROOT),
            (["npm", "run", "dev", "--", "--host", "127.0.0.1", "--strictPort", *frontend_args], ROOT / "frontend"),
        ):
            children.append(subprocess.Popen(command, cwd=cwd, start_new_session=True))
        print("API: http://127.0.0.1:8000 · UI address is printed by Vite below.", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.3)
        return next((child.returncode for child in children if child.returncode is not None), 0) or 0
    except KeyboardInterrupt:
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
