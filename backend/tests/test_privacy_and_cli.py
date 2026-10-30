import json
import os
import subprocess
import sys
from pathlib import Path

from app.storage import TicketStore


def test_sqlite_sidecars_owner_only(tmp_path):
    parent = tmp_path / "preexisting-public-dir"; parent.mkdir(mode=0o755)
    path = parent / "private.sqlite"
    store = TicketStore(str(path))
    try:
        for file in parent.iterdir():
            assert file.stat().st_mode & 0o077 == 0
    finally:
        store.close()


def test_predict_atomic_private_outputs(tmp_path):
    source, output = tmp_path / "input.jsonl", tmp_path / "pred.jsonl"
    source.write_text(json.dumps({"kind":"report","messages":[{"role":"player","text":"Где найти работу?"}]}) + "\n{broken\n")
    output.write_text("existing-result")
    env = os.environ | {"PYTHONPATH":str(Path(__file__).resolve().parents[1]), "APP_MODE":"test", "ENABLE_GROQ":"false"}
    args = [sys.executable,"-m","app.cli","predict","--input",str(source),"--output",str(output)]
    bad = subprocess.run(args, env=env, capture_output=True, text=True)
    assert bad.returncode == 2 and output.read_text() == "existing-result"
    source.write_text(source.read_text().splitlines()[0] + "\n")
    good = subprocess.run(args, env=env, capture_output=True, text=True)
    assert good.returncode == 0, good.stderr
    assert output.stat().st_mode & 0o077 == 0
    assert json.loads(output.read_text())["category"] == "report.question"
    assert not list(tmp_path.glob(".copilot-*"))
