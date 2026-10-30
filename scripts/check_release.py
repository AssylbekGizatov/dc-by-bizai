#!/usr/bin/env python3
"""Fail on obvious private data, generated artifacts, or credentials in a release.

Scans tracked files plus untracked non-ignored candidates. This is a guardrail,
not proof that arbitrary text or images contain no private information.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_DIRS = {
    "data", "datasets", "private", "raw", "derived", "samples", "outputs",
    "predictions", "embeddings", "indexes", "cache", "node_modules", ".venv", "dist",
}
BLOCKED_ENDINGS = (".jsonl", ".jsonl.gz", ".csv", ".tsv", ".parquet", ".arrow",
                   ".sqlite", ".sqlite3", ".db", ".npz", ".npy", ".zip", ".gz",
                   ".tgz", ".tar", ".bz2", ".xz", ".7z", ".pem", ".key",
                   ".safetensors", ".bin", ".pt", ".pth", ".onnx")
# Preserve the original, reviewed design image. New binaries need explicit review.
REVIEWED_BINARY_BLOBS = {"docs/user-flow.png": "7d5865a3d910e40611948d0334c8959001453e55"}
SECRET_PATTERNS = (
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{32,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def inspect_file(relative: str, content: bytes) -> list[str]:
    path = Path(relative)
    errors = []
    if len(content) > 2_000_000:
        errors.append("file exceeds 2 MB; review before release")
    if any(part in BLOCKED_DIRS for part in path.parts):
        errors.append("private/generated directory")
    if relative.lower().endswith(BLOCKED_ENDINGS):
        errors.append("private data or secret-bearing file type")
    if path.name in {"rules.json", "taxonomy.json"} or path.name.startswith("tickets_"):
        errors.append("challenge-data filename")
    if path.name.startswith(".env") and path.name != ".env.example":
        errors.append("environment file")
    if path.is_absolute() or ".." in path.parts:
        errors.append("non-repository path")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = ""
        blob_id = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        if REVIEWED_BINARY_BLOBS.get(relative) != blob_id:
            errors.append("unreviewed binary artifact")
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        errors.append("credential-like content (value redacted)")
    return errors


def main() -> int:
    command = ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    raw = subprocess.check_output(command, cwd=ROOT)
    paths = sorted(set(raw.decode("utf-8").split("\0")) - {""})
    issues: list[str] = []
    for relative in paths:
        path = ROOT / relative
        if path.is_symlink():
            issues.append(f"{relative}: symlink requires manual release review")
            continue
        if not path.is_file():
            continue
        for issue in inspect_file(relative, path.read_bytes()):
            issues.append(f"{relative}: {issue}")
    if issues:
        print("Release hygiene failed:\n" + "\n".join(issues), file=sys.stderr)
        return 1
    print(f"Release hygiene passed ({len(paths)} candidate files). Manually review the diff before publishing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
