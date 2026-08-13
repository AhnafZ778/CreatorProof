import argparse
import csv
import json
import subprocess

import pytest
from PIL import Image

from scripts.clipdet_json_adapter import _run, llr_to_score


def test_clipdet_llr_mapping_preserves_official_zero_decision_boundary():
    assert llr_to_score(0.0) == 0.5
    assert llr_to_score(2.0) > 0.5
    assert llr_to_score(-2.0) < 0.5
    assert llr_to_score(1000.0) == pytest.approx(1.0)


def test_clipdet_adapter_uses_upstream_fusion_column(monkeypatch, tmp_path):
    repo = tmp_path / "clipdet"
    weights = repo / "weights"
    repo.mkdir()
    weights.mkdir()
    (repo / "main.py").write_text("# test entrypoint\n", encoding="utf-8")
    image_path = tmp_path / "input.png"
    Image.new("RGB", (32, 32), "white").save(image_path)

    def fake_run(command, **kwargs):
        del kwargs
        output_path = command[command.index("--out_csv") + 1]
        with open(output_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["filename", "clipdet_latent10k_plus", "Corvi2023", "fusion"],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "filename": str(image_path),
                    "clipdet_latent10k_plus": -4.0,
                    "Corvi2023": -3.0,
                    "fusion": 2.0,
                }
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    payload = _run(
        argparse.Namespace(
            repo=repo,
            weights=weights,
            image=image_path,
            models="clipdet_latent10k_plus,Corvi2023",
            fusion="soft_or_prob",
            device="cpu",
            runner_python=None,
            timeout_seconds=5,
        )
    )

    assert payload["score"] == pytest.approx(llr_to_score(2.0))
    assert payload["diagnostics"]["fused_llr"] == 2.0
    assert payload["score_semantics"] == (
        "SIGMOID_OF_OFFICIAL_FUSED_LLR_NOT_DEPLOYMENT_PROBABILITY"
    )


def test_clipdet_adapter_sends_manifest_images_through_one_upstream_run(monkeypatch, tmp_path):
    repo = tmp_path / "clipdet"
    weights = repo / "weights"
    repo.mkdir()
    weights.mkdir()
    (repo / "main.py").write_text("# test entrypoint\n", encoding="utf-8")
    image_paths = []
    for index in range(3):
        image_path = tmp_path / f"input-{index}.png"
        Image.new("RGB", (32, 32), (20 * index, 40, 80)).save(image_path)
        image_paths.append(image_path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "creatorproof.synthetic_batch.v1",
                "items": [
                    {"id": f"view-{index}", "path": str(path)}
                    for index, path in enumerate(image_paths)
                ],
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_run(command, **kwargs):
        del kwargs
        calls.append(command)
        input_path = command[command.index("--in_csv") + 1]
        output_path = command[command.index("--out_csv") + 1]
        with open(input_path, encoding="utf-8", newline="") as input_handle:
            input_rows = list(csv.DictReader(input_handle))
        with open(output_path, "w", encoding="utf-8", newline="") as output_handle:
            writer = csv.DictWriter(
                output_handle,
                fieldnames=["filename", "clipdet_latent10k_plus", "Corvi2023", "fusion"],
            )
            writer.writeheader()
            for index, row in enumerate(input_rows):
                writer.writerow(
                    {
                        "filename": row["filename"],
                        "clipdet_latent10k_plus": 0.2,
                        "Corvi2023": 0.4,
                        "fusion": 1.0 + index,
                    }
                )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    payload = _run(
        argparse.Namespace(
            repo=repo,
            weights=weights,
            image=None,
            manifest=manifest,
            models="clipdet_latent10k_plus,Corvi2023",
            fusion="soft_or_prob",
            device="cpu",
            runner_python=None,
            timeout_seconds=5,
        )
    )

    assert len(calls) == 1
    assert payload["schema"] == "creatorproof.synthetic_batch_result.v1"
    assert [item["id"] for item in payload["results"]] == ["view-0", "view-1", "view-2"]
    assert payload["results"][2]["score"] > payload["results"][0]["score"]
