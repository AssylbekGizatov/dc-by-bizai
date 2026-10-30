#!/usr/bin/env python3
"""Run browser E2E against real loopback APIs and disposable SQLite files.

The third API injects a mock provider failure; it never calls Groq.
"""
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def main():
    processes=[]
    with tempfile.TemporaryDirectory(prefix='copilot-e2e-') as directory:
        env=dict(os.environ, PYTHONUTF8='1', API_TOKEN=secrets.token_urlsafe(32), ENABLE_GROQ='false',
                 APP_MODE='test', FRONTEND_DIST=str(ROOT/'frontend/dist'), PYTHONPATH=str(ROOT/'backend'))
        env.update(E2E_URL='http://127.0.0.1:18080', E2E_RATE_URL='http://127.0.0.1:18082',
                   E2E_MODEL_ERROR_URL='http://127.0.0.1:18084')
        try:
            for port,limit in [(18080,'1000'),(18082,'4'),(18084,'1000')]:
                child_env=dict(env, DATABASE_PATH=str(Path(directory)/f'{port}.sqlite3'),REQUEST_RATE_PER_MINUTE=limit)
                log=open(Path(directory)/f'{port}.log','wb')
                app_arguments = ['failing_provider:factory','--factory','--app-dir','scripts/e2e'] if port == 18084 else ['app.main:app','--app-dir','backend']
                process=subprocess.Popen([sys.executable,'-m','uvicorn',*app_arguments,
                                          '--host','127.0.0.1','--port',str(port),'--no-access-log','--no-proxy-headers'],cwd=ROOT,
                                         env=child_env,stdout=log,stderr=log)
                processes.append((process,log))
                deadline=time.monotonic()+40
                while time.monotonic()<deadline:
                    if process.poll() is not None: raise RuntimeError(f'E2E API {port} failed to start')
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/ready',timeout=1) as response:
                            if response.status==200:break
                    except OSError:time.sleep(.2)
                else:raise RuntimeError(f'E2E API {port} readiness timed out')
            return subprocess.call(['node',str(ROOT/'node_modules/@playwright/test/cli.js'),'test',*sys.argv[1:]],cwd=ROOT,env=env)
        finally:
            for process,log in processes:
                if process.poll() is None:
                    if os.name == 'nt':
                        # A venv python.exe is a launcher on Windows. Stop its owned
                        # process tree so the real interpreter releases SQLite/logs.
                        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                    else:
                        process.terminate()
                try: process.wait(timeout=8)
                except subprocess.TimeoutExpired: process.kill();process.wait()
                log.close()


if __name__=='__main__':raise SystemExit(main())
