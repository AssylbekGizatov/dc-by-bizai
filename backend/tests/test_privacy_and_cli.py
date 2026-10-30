import json
import os
import subprocess
import sys
from pathlib import Path

from app.storage import TicketStore


def assert_private_permissions(path):
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0
        return
    import ctypes
    from ctypes import wintypes
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    security.GetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p,
                                          wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    security.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    size = wintypes.DWORD()
    security.GetFileSecurityW(str(path), 4, None, 0, ctypes.byref(size))
    buffer = ctypes.create_string_buffer(size.value)
    assert security.GetFileSecurityW(str(path), 4, buffer, size, ctypes.byref(size))
    value = wintypes.LPWSTR()
    assert security.ConvertSecurityDescriptorToStringSecurityDescriptorW(buffer, 1, 4, ctypes.byref(value), None)
    try:
        dacl = value.value
        assert dacl.startswith("D:P"), dacl  # No inherited grants from a public parent.
        assert dacl.count("(A;") == 3, dacl
        assert ";;;SY)" in dacl and ";;;BA)" in dacl and ";;;S-1-" in dacl
        assert not any(f";;;{group})" in dacl for group in ("WD", "AU", "BU")), dacl
    finally:
        kernel.LocalFree(ctypes.cast(value, ctypes.c_void_p))


def test_sqlite_sidecars_owner_only(tmp_path):
    parent = tmp_path / "preexisting-public-dir"; parent.mkdir(mode=0o755)
    path = parent / "private.sqlite"
    store = TicketStore(str(path))
    try:
        for file in parent.iterdir():
            assert_private_permissions(file)
    finally:
        store.close()


def test_predict_atomic_private_outputs(tmp_path):
    source, output = tmp_path / "input.jsonl", tmp_path / "pred.jsonl"
    source.write_text(json.dumps({"kind":"report","messages":[{"role":"player","text":"Где найти работу?"}]}) + "\n{broken\n")
    output.write_text("existing-result")
    env = os.environ | {"PYTHONPATH":str(Path(__file__).resolve().parents[1]), "APP_MODE":"test", "ENABLE_GROQ":"false"}
    args = [sys.executable,"-m","app.cli","predict","--input",str(source),"--output",str(output),"--allow-synthetic-rules"]
    bad = subprocess.run(args, env=env, capture_output=True, text=True)
    assert bad.returncode == 2 and output.read_text() == "existing-result"
    source.write_text(source.read_text().splitlines()[0] + "\n")
    good = subprocess.run(args, env=env, capture_output=True, text=True)
    assert good.returncode == 0, good.stderr
    assert_private_permissions(output)
    assert json.loads(output.read_text())["category"] == "report.question"
    assert not list(tmp_path.glob(".copilot-*"))


def test_predict_requires_real_rules_and_keeps_ticket_id(tmp_path):
    source, output = tmp_path / "input.jsonl", tmp_path / "pred.jsonl"
    source.write_text(json.dumps({"ticket_id":"synthetic-1","kind":"report","messages":[{"role":"player","text":"Где найти работу?"}]}) + "\n")
    env = {k: v for k, v in os.environ.items() if k != "RULES_PATH"} | {"PYTHONPATH":str(Path(__file__).resolve().parents[1]), "APP_MODE":"test", "ENABLE_GROQ":"false"}
    args = [sys.executable,"-m","app.cli","predict","--input",str(source),"--output",str(output)]
    missing = subprocess.run(args, env=env, capture_output=True, text=True)
    assert missing.returncode == 2 and "RULES_PATH" in missing.stderr and not output.exists()
    good = subprocess.run(args + ["--allow-synthetic-rules"], env=env, capture_output=True, text=True)
    assert good.returncode == 0, good.stderr
    row = json.loads(output.read_text())
    assert list(row)[0] == "ticket_id" and row["ticket_id"] == "synthetic-1"
