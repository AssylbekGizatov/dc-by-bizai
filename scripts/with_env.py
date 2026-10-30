#!/usr/bin/env python3
"""Run a command with optional local .env values, without executing shell syntax."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]


def read_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        name, separator, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError(f"Invalid .env entry on line {number}; expected NAME=value")
        if value.startswith(("'", '"')):
            parts = shlex.split(value, comments=True, posix=True)
            if len(parts) != 1:
                raise ValueError(f"Invalid quoted .env value on line {number}")
            value = parts[0]
        else:
            # A space followed by # begins a comment; otherwise preserve literals.
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        result[name] = value
    return result


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python scripts/with_env.py COMMAND [ARG ...]")
    env = read_env(ROOT / ".env") | dict(os.environ)
    os.chdir(ROOT)
    os.execvpe(sys.argv[1], sys.argv[1:], env)


if __name__ == "__main__":
    main()
