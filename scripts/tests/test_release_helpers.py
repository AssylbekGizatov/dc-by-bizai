from __future__ import annotations

import importlib.util
import ast
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]


def module(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_env_is_literal_and_supports_comments(tmp_path: Path):
    env = tmp_path / "environment"
    env.write_text('A=one # comment\nB="two words"\nC=$(touch nope)\nD=${HOME}\nEMPTY=\nexport E=ok\n')
    assert module("with_env").read_env(env) == {
        "A": "one", "B": "two words", "C": "$(touch nope)", "D": "${HOME}", "EMPTY": "", "E": "ok",
    }
    assert not (tmp_path / "nope").exists()


def test_env_rejects_invalid_name_without_echoing_value(tmp_path: Path):
    env = tmp_path / "environment"
    env.write_text("bad key=private-value\n")
    with pytest.raises(ValueError, match="line 1") as error:
        module("with_env").read_env(env)
    assert "private-value" not in str(error.value)


@pytest.mark.parametrize("name", ["data/a.json", ".env", "tickets_valid.jsonl", "rules.json", "foo.sqlite3", "node_modules/a.js", "handout.tgz", "archive.tar", "archive.bz2", "archive.xz", "archive.7z"])
def test_release_rejects_private_paths(name: str):
    assert module("check_release").inspect_file(name, b"{}")


def test_release_allows_synthetic_fixture_and_example_env():
    checker = module("check_release")
    assert not checker.inspect_file("backend/fixtures/synthetic_rules.json", b'{"synthetic": true}')
    assert not checker.inspect_file(".env.example", b"GROQ_API_KEY=\n")


def test_release_redacts_a_key():
    key = ("gs" + "k_") + "A" * 32
    errors = module("check_release").inspect_file("README.md", key.encode())
    assert errors and key not in repr(errors)


def test_release_rejects_unknown_binary():
    assert module("check_release").inspect_file("arbitrary.png", b"\x89PNG\x00")


def test_root_model_defaults_match_backend_without_loading_secrets():
    root = SCRIPTS.parent
    tree = ast.parse((root / "backend/app/config.py").read_text())
    defaults = [node.args[1].value for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "getenv" and len(node.args) > 1
                and isinstance(node.args[0], ast.Constant) and node.args[0].value == "GROQ_MODEL"
                and isinstance(node.args[1], ast.Constant)]
    assert len(defaults) == 1
    default = defaults[0]
    assert module("with_env").read_env(root / ".env.example")["GROQ_MODEL"] == default
    assert "${GROQ_MODEL:-" + default + "}" in (root / "compose.yaml").read_text()
    assert f"`{default}`" in (root / "README.md").read_text()
