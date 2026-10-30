#!/usr/bin/env python3
"""Explicit, pinned download of the optional local encoder (stdlib only).

Never called by the application. No credentials, external inference, remote Python
code, pickle weights, or datasets are used. The destination must be outside Git.
Use --verify-only to check an existing installation without any network access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


REPO_ID = "intfloat/multilingual-e5-small"
REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
REPO_ROOT = Path(__file__).resolve().parents[1]
# Sizes and SHA-256 digests verified against the pinned official HF snapshot.
# The safetensors digest also matches Hugging Face's x-linked-etag.
FILES = {
    "README.md": (497538, "0038de97aee16258cecbad7ffda4b4febd6953e747a00e0ddbc8e6ed241e9c1c"),
    "config.json": (655, "69137736cab8b8903a07fe8afaafdda25aac55415a12a55d1bffa9f581abf959"),
    "modules.json": (387, "c6e29747481e8b5dd2b58401966aeac910de39092f90cda9a704b1545f902b04"),
    "sentence_bert_config.json": (57, "948201d8329907aae938fa62f9ceeed53f5694dacc2b87b9f3b78b37ee986529"),
    "1_Pooling/config.json": (200, "987f7a67a38fa564c849bb5d277c52ab9088a84368fc0be31a354125aebb12a0"),
    "tokenizer_config.json": (443, "a1d6bc8734a6f635dc158508bef000f8e2e5a759c7d92f984b2c86e5ff53425b"),
    "special_tokens_map.json": (167, "d05497f1da52c5e09554c0cd874037a083e1dc1b9cfd48034d1c717f1afc07a7"),
    "tokenizer.json": (17082730, "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39"),
    "sentencepiece.bpe.model": (5069051, "cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865"),
    "model.safetensors": (470641600, "1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477"),
}
ALLOWED_HOSTS = {"huggingface.co", "us.aws.cdn.hf.co", "cas-bridge.xethub.hf.co"}
MODEL_MODULES = {
    "sentence_transformers.models.Transformer",
    "sentence_transformers.models.Pooling",
    "sentence_transformers.models.Normalize",
}


def check_url(url: str) -> None:
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("Download redirect is not an approved HTTPS model-registry host")


class RegistryRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def destination(raw: str) -> Path:
    result = Path(raw).expanduser().resolve()
    if result == REPO_ROOT or result.is_relative_to(REPO_ROOT):
        raise ValueError("Model destination must be outside the application repository")
    for parent in (result, *result.parents):
        marker = parent / ".git"
        if marker.is_file() or (marker / "HEAD").is_file():
            raise ValueError("Model destination must be outside all Git working trees")
    return result


def safe_target(root: Path, name: str) -> Path:
    target = root / name
    if target.is_symlink() or not target.resolve().is_relative_to(root):
        raise ValueError("Model files must not be symlinks or escape the model directory")
    return target


def verify_file(path: Path, size: int, expected: str) -> None:
    if not path.is_file() or path.is_symlink() or path.stat().st_size != size:
        raise ValueError(f"Missing or incorrect-size model file: {path.name}")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != expected:
        raise ValueError(f"SHA-256 mismatch for model file: {path.name}")


def download_file(opener, root: Path, name: str, size: int, expected: str) -> None:
    target = safe_target(root, name)
    if target.exists():
        # Never overwrite a pre-existing mismatched artifact silently.
        verify_file(target, size, expected)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://huggingface.co/{REPO_ID}/resolve/{REVISION}/{name}"
    check_url(url)
    request = Request(url, headers={"User-Agent": "GrandMobile-LocalEncoder-Setup/1"})
    temporary = None
    deadline = time.monotonic() + 900
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".download-", delete=False) as output:
            temporary = Path(output.name)
            received = 0
            with opener.open(request, timeout=30) as response:
                while True:
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"Download exceeded 15 minutes: {name}")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > size:
                        raise ValueError(f"Registry file exceeds pinned size: {name}")
                    output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        verify_file(temporary, size, expected)
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def verify_model(root: Path) -> None:
    for name, (size, digest) in FILES.items():
        verify_file(safe_target(root, name), size, digest)
    config = json.loads((root / "config.json").read_text())
    tokenizer = json.loads((root / "tokenizer_config.json").read_text())
    modules = json.loads((root / "modules.json").read_text())
    if config.get("model_type") != "bert" or config.get("architectures") != ["BertModel"]:
        raise ValueError("Only the expected built-in BertModel architecture is allowed")
    if "auto_map" in config or "auto_map" in tokenizer:
        raise ValueError("Remote-code auto_map configurations are forbidden")
    if any(module.get("type") not in MODEL_MODULES for module in modules):
        raise ValueError("Only built-in SentenceTransformer modules are allowed")
    if any(root.rglob("*.py")) or any(root.rglob("*.bin")):
        raise ValueError("Remove executable Python or pickle .bin weights from model directory")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, help="Model directory outside every Git working tree")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--download", action="store_true", help="Explicitly fetch ~493 MB from official Hugging Face")
    action.add_argument("--verify-only", action="store_true", help="Verify files, with no network or writes")
    args = parser.parse_args(argv)
    try:
        root = destination(args.destination)
        if args.download:
            root.mkdir(parents=True, exist_ok=True)
            opener = build_opener(RegistryRedirects())
            for name, (size, digest) in FILES.items():
                download_file(opener, root, name, size, digest)
                print(f"Verified {name}", flush=True)
        verify_model(root)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Model setup failed: {exc}\n")
    print(json.dumps({"model": REPO_ID, "revision": REVISION, "destination": str(root),
                      "bytes": sum(size for size, _ in FILES.values()), "files_verified": len(FILES),
                      "license": "MIT declared in pinned model card", "remote_code": False,
                      "weights": "safetensors only", "external_inference_calls": 0}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
