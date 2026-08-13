import hashlib
from types import SimpleNamespace

import pytest
import torch

from app.providers.style_retrieval import CSDStyleEmbeddingProvider, StyleProviderUnavailable


def _csd_layout(tmp_path):
    repo = tmp_path / "CSD-repo"
    package = repo / "CSD"
    package.mkdir(parents=True)
    for name in ("model.py", "utils.py", "loss_utils.py"):
        (package / name).write_text("# test module\n", encoding="utf-8")
    checkpoint = tmp_path / "model.bin"
    checkpoint.write_bytes(b"exact-csd-checkpoint")
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    return repo, checkpoint, digest


def test_csd_requires_checkpoint_digest_before_loading(tmp_path):
    repo, checkpoint, _ = _csd_layout(tmp_path)
    provider = CSDStyleEmbeddingProvider(repo, checkpoint)

    assert provider.available is False
    assert provider.unavailable_reason == "CSD_CHECKPOINT_EXPECTED_SHA256_REQUIRED"


def test_csd_rejects_repository_revision_drift(tmp_path, monkeypatch):
    repo, checkpoint, digest = _csd_layout(tmp_path)
    provider = CSDStyleEmbeddingProvider(
        repo,
        checkpoint,
        expected_sha256=digest,
        expected_repo_revision="a" * 40,
    )
    monkeypatch.setattr(provider, "_actual_repo_revision", lambda: "b" * 40)

    assert provider.available is False
    assert provider.unavailable_reason == "CSD_REPO_REVISION_MISMATCH"


def test_csd_rejects_imported_modules_outside_pinned_checkout(tmp_path):
    repo, checkpoint, digest = _csd_layout(tmp_path)
    provider = CSDStyleEmbeddingProvider(repo, checkpoint, expected_sha256=digest)

    with pytest.raises(StyleProviderUnavailable, match="MODULE_ORIGIN_MISMATCH"):
        provider._verify_module_origin(SimpleNamespace(__file__=tmp_path / "other" / "model.py"))


def test_csd_loads_exact_state_dict_strictly(tmp_path, monkeypatch):
    repo, checkpoint, digest = _csd_layout(tmp_path)
    provider = CSDStyleEmbeddingProvider(repo, checkpoint, expected_sha256=digest)
    observed: dict[str, object] = {}

    class FakeModel:
        def load_state_dict(self, state, *, strict):
            observed["state"] = state
            observed["strict"] = strict

        def eval(self):
            return self

        def to(self, device):
            observed["device"] = device
            return self

    package = repo / "CSD"
    modules = {
        "CSD.model": SimpleNamespace(
            __file__=package / "model.py",
            CSD_CLIP=lambda *_args: FakeModel(),
        ),
        "CSD.utils": SimpleNamespace(
            __file__=package / "utils.py",
            convert_state_dict=lambda state: {"converted": state["weight"]},
        ),
        "CSD.loss_utils": SimpleNamespace(
            __file__=package / "loss_utils.py",
            transforms_branch0=object(),
        ),
    }
    monkeypatch.setattr(
        "app.providers.style_retrieval.importlib.import_module",
        lambda name: modules[name],
    )
    monkeypatch.setattr(
        torch,
        "load",
        lambda *_args, **_kwargs: {"model_state_dict": {"weight": "exact"}},
    )

    provider._ensure_loaded()

    assert observed["strict"] is True
    assert observed["state"] == {"converted": "exact"}
    assert observed["device"] == "cpu"
