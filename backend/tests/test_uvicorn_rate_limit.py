"""Real TCP regression: forwarded headers must not bypass the direct-peer quota."""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import shlex
import socket
import subprocess
import sys
import time

import httpx


ROOT = Path(__file__).resolve().parents[2]


def test_documented_uvicorn_launch_keeps_auth_and_rate_limit_with_rotating_headers(tmp_path):
    # Exercise the documented serve command, including Uvicorn's outer middleware,
    # rather than TestClient (which does not run ProxyHeadersMiddleware).
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    serve_line = makefile.split("\nserve:\n", 1)[1].splitlines()[0]
    arguments = shlex.split(serve_line)
    uvicorn_args = arguments[arguments.index("uvicorn") + 1:]
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    uvicorn_args[uvicorn_args.index("--port") + 1] = str(port)
    token = secrets.token_urlsafe(32)
    env = os.environ | {
        "APP_MODE": "test", "PYTHONUTF8": "1", "DATABASE_PATH": str(tmp_path / "queue.sqlite3"),
        "API_TOKEN": token, "ENABLE_GROQ": "false", "REQUEST_RATE_PER_MINUTE": "3",
        # Even a broad pre-existing proxy environment must not undo the launch flag.
        "FORWARDED_ALLOW_IPS": "*",
    }
    for name in ("GROQ_API_KEY", "RULES_PATH", "TAXONOMY_PATH", "LOCAL_ENCODER_PATH", "FRONTEND_DIST"):
        env.pop(name, None)
    with (tmp_path / "uvicorn.log").open("wb") as log:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", *uvicorn_args], cwd=ROOT,
                                   env=env, stdout=log, stderr=log)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5, trust_env=False) as client:
                deadline = time.monotonic() + 40
                while True:
                    assert process.poll() is None, "Synthetic Uvicorn process exited during startup"
                    try:
                        if client.get("/ready").status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    assert time.monotonic() < deadline, "Synthetic Uvicorn readiness timed out"
                    time.sleep(.1)

                def rotating_headers(number, *, authorized=True):
                    address = f"198.51.100.{number}"
                    headers = {"X-Forwarded-For": address, "Forwarded": f"for={address};proto=https",
                               "X-Real-IP": address, "X-Forwarded-Proto": "https"}
                    if authorized:
                        headers["Authorization"] = "Bearer " + token
                    return headers

                denied = client.get("/api/tickets", headers=rotating_headers(1, authorized=False))
                assert denied.status_code == 401 and denied.headers["WWW-Authenticate"] == "Bearer"
                for number in (2, 3):
                    accepted = client.get("/api/tickets", headers=rotating_headers(number))
                    assert accepted.status_code == 200 and accepted.json()["total"] == 0
                for number in (4, 5, 6):
                    limited = client.get("/api/tickets", headers=rotating_headers(number))
                    assert limited.status_code == 429
                    assert 1 <= int(limited.headers["Retry-After"]) <= 60
                    assert limited.headers["Cache-Control"] == "no-store"
                assert client.get("/ready").status_code == 200
        finally:
            if process.poll() is None:
                if os.name == "nt":
                    # Windows venv Python owns an interpreter child: close only this tree.
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                else:
                    process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
