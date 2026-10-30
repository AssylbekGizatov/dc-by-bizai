"""Downloader invariants; all fixtures are synthetic and no network is used."""
import hashlib
import importlib.util
import io
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location("fetch_local_encoder", Path(__file__).parents[1] / "fetch_local_encoder.py")
fetch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch)


class FakeOpener:
    def __init__(self, body):
        self.body = body
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return io.BytesIO(self.body)


def test_explicit_action_is_required(tmp_path):
    with pytest.raises(SystemExit) as exc:
        fetch.main(["--destination", str(tmp_path / "model")])
    assert exc.value.code == 2


def test_rejects_repository_and_other_git_worktrees(tmp_path):
    with pytest.raises(ValueError):
        fetch.destination(str(fetch.REPO_ROOT / "model"))
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main")
    with pytest.raises(ValueError):
        fetch.destination(str(tmp_path / "model"))


@pytest.mark.parametrize("url", ["http://huggingface.co/model", "https://evil.example/model", "https://huggingface.co.evil.example/model", "https://token@huggingface.co/model", "https://huggingface.co:444/model"])
def test_rejects_unsafe_download_urls(url):
    with pytest.raises(ValueError):
        fetch.check_url(url)


def test_atomic_verified_download_and_idempotent_reuse(tmp_path):
    body = b"synthetic public config"
    digest = hashlib.sha256(body).hexdigest()
    opener = FakeOpener(body)
    fetch.download_file(opener, tmp_path, "config.json", len(body), digest)
    fetch.download_file(opener, tmp_path, "config.json", len(body), digest)
    assert (tmp_path / "config.json").read_bytes() == body
    assert len(opener.requests) == 1
    request, timeout = opener.requests[0]
    assert fetch.REVISION in request.full_url
    assert not request.has_header("Authorization") and timeout == 30
    assert not list(tmp_path.glob(".download-*"))


@pytest.mark.parametrize("body,size,digest", [(b"bad", 3, "0" * 64), (b"oversize", 3, "0" * 64), (b"short", 10, "0" * 64)])
def test_integrity_failure_leaves_no_artifact(tmp_path, body, size, digest):
    with pytest.raises(ValueError):
        fetch.download_file(FakeOpener(body), tmp_path, "config.json", size, digest)
    assert not (tmp_path / "config.json").exists()
    assert not list(tmp_path.iterdir())


def test_existing_invalid_file_is_not_overwritten(tmp_path):
    target = tmp_path / "config.json"
    target.write_bytes(b"keep")
    opener = FakeOpener(b"replacement")
    with pytest.raises(ValueError):
        fetch.download_file(opener, tmp_path, "config.json", 11, hashlib.sha256(b"replacement").hexdigest())
    assert target.read_bytes() == b"keep"
    assert not opener.requests


def test_symlink_escape_is_rejected(tmp_path):
    root = tmp_path / "model"
    root.mkdir()
    (root / "1_Pooling").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        fetch.safe_target(root, "1_Pooling/config.json")


def test_verify_only_does_not_create_directory_or_network(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "build_opener", lambda *_: pytest.fail("network must not initialize"))
    target = tmp_path / "absent"
    with pytest.raises(SystemExit) as exc:
        fetch.main(["--destination", str(target), "--verify-only"])
    assert exc.value.code == 1
    assert not target.exists()


def test_allowlist_excludes_python_and_pickle_weights():
    assert "model.safetensors" in fetch.FILES
    assert not any(name.endswith((".py", ".bin")) for name in fetch.FILES)
    assert len(fetch.REVISION) == 40
