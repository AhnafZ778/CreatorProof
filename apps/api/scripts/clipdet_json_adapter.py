from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def llr_to_score(log_likelihood_ratio: float) -> float:
    """Map the official detector's signed LLR to a bounded fusion signal.

    The result is intentionally reported as uncalibrated. A zero LLR maps to
    0.5 and the deployment calibration registry remains the only component that
    may attach domain-calibrated semantics.
    """

    bounded = max(min(float(log_likelihood_ratio), 50.0), -50.0)
    return 1.0 / (1.0 + math.exp(-bounded))


def _inputs(args: argparse.Namespace) -> list[tuple[str, Path]]:
    image_value = getattr(args, "image", None)
    manifest_value = getattr(args, "manifest", None)
    if bool(image_value) == bool(manifest_value):
        raise RuntimeError("EXACTLY_ONE_OF_IMAGE_OR_MANIFEST_IS_REQUIRED")
    if image_value:
        image = Path(image_value).resolve()
        if not image.is_file():
            raise RuntimeError("INPUT_IMAGE_NOT_FOUND")
        return [("0", image)]

    manifest_path = Path(manifest_value).resolve()
    if not manifest_path.is_file():
        raise RuntimeError("INPUT_MANIFEST_NOT_FOUND")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema") != "creatorproof.synthetic_batch.v1":
        raise RuntimeError("INPUT_MANIFEST_SCHEMA_INVALID")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise RuntimeError("INPUT_MANIFEST_ITEMS_INVALID")
    inputs = []
    seen_ids: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict) or item.get("id") is None or item.get("path") is None:
            raise RuntimeError("INPUT_MANIFEST_ITEM_INVALID")
        item_id = str(item["id"])
        path = Path(str(item["path"])).resolve()
        if item_id in seen_ids or not path.is_file():
            raise RuntimeError("INPUT_MANIFEST_ITEM_INVALID")
        seen_ids.add(item_id)
        inputs.append((item_id, path))
    return inputs


def _score_payload(args: argparse.Namespace, *, fused_llr: float, member_llrs: dict) -> dict:
    return {
        "provider": "grip-clipdet-official-adapter",
        "version": f"official-main-{args.fusion}",
        "score": llr_to_score(fused_llr),
        "calibrated": False,
        "score_semantics": "SIGMOID_OF_OFFICIAL_FUSED_LLR_NOT_DEPLOYMENT_PROBABILITY",
        "source_scope": "CLIP_SEMANTIC_PLUS_FORENSIC_PIXEL_MODELS",
        "diagnostics": {
            "official_fusion": args.fusion,
            "fused_llr": fused_llr,
            "member_llrs": member_llrs,
        },
        "warnings": [
            "DEPLOYMENT_CALIBRATION_REQUIRED",
            "ADAPTER_CALLS_OPERATOR_INSTALLED_OFFICIAL_REPOSITORY",
        ],
    }


def _run_batch(args: argparse.Namespace) -> list[dict]:
    repo = args.repo.resolve()
    entrypoint = repo / "main.py"
    weights = args.weights.resolve()
    inputs = _inputs(args)
    if not entrypoint.is_file():
        raise RuntimeError("CLIPDET_ENTRYPOINT_NOT_FOUND")
    if not weights.is_dir():
        raise RuntimeError("CLIPDET_WEIGHTS_DIRECTORY_NOT_FOUND")
    if args.runner_python:
        runner_python = os.path.abspath(args.runner_python)
    else:
        runner_python = sys.executable
    if not Path(runner_python).is_file():
        raise RuntimeError("CLIPDET_RUNNER_PYTHON_NOT_FOUND")

    models = [item.strip() for item in args.models.split(",") if item.strip()]
    if not models:
        raise RuntimeError("CLIPDET_MODEL_LIST_EMPTY")

    with tempfile.TemporaryDirectory(prefix="creatorproof-clipdet-") as temp_dir:
        temp_root = Path(temp_dir)
        input_csv = temp_root / "input.csv"
        output_csv = temp_root / "output.csv"
        with input_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["filename"])
            writer.writeheader()
            writer.writerows({"filename": str(path)} for _, path in inputs)
        command = [
            runner_python,
            str(entrypoint),
            "--in_csv",
            str(input_csv),
            "--out_csv",
            str(output_csv),
            "--weights_dir",
            str(weights),
            "--models",
            ",".join(models),
            "--fusion",
            args.fusion,
            "--device",
            args.device,
        ]
        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)
        env.pop("PYTHONPATH", None)
        env.pop("UV_PROJECT_ENVIRONMENT", None)
        print(f"DEBUG COMMAND: {command}", file=sys.stderr)
        completed = subprocess.run(
            command,
            cwd=repo,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=args.timeout_seconds,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"CLIPDET_NONZERO_EXIT: {completed.stderr}")
        if not output_csv.is_file():
            raise RuntimeError("CLIPDET_OUTPUT_NOT_CREATED")
        with output_csv.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if len(rows) != len(inputs):
            raise RuntimeError("CLIPDET_OUTPUT_ROW_COUNT_INVALID")
        try:
            rows_by_path = {str(Path(str(row["filename"])).resolve()): row for row in rows}
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("CLIPDET_OUTPUT_FILENAME_INVALID") from exc

        results = []
        for item_id, image_path in inputs:
            row = rows_by_path.get(str(image_path))
            if row is None:
                raise RuntimeError("CLIPDET_OUTPUT_FILENAME_MISMATCH")
            try:
                fused_llr = float(row["fusion"])
                member_llrs = {model: float(row[model]) for model in models}
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError("CLIPDET_FUSION_OUTPUT_INVALID") from exc
            results.append(
                {
                    "id": item_id,
                    **_score_payload(
                        args,
                        fused_llr=fused_llr,
                        member_llrs=member_llrs,
                    ),
                }
            )
    return results


def _run(args: argparse.Namespace) -> dict:
    results = _run_batch(args)
    if getattr(args, "manifest", None):
        return {
            "schema": "creatorproof.synthetic_batch_result.v1",
            "results": results,
        }
    return {key: value for key, value in results[0].items() if key != "id"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the official GRIP CLIP detector and emit CreatorProof JSON."
    )
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--image", type=Path)
    inputs.add_argument(
        "--manifest",
        type=Path,
        help="CreatorProof batch manifest; all listed views run in one model process.",
    )
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument(
        "--runner-python",
        default=None,
        help="Optional Python executable for an isolated official-repository environment.",
    )
    parser.add_argument("--models", default="clipdet_latent10k_plus,Corvi2023")
    parser.add_argument("--fusion", default="soft_or_prob")
    parser.add_argument("--timeout-seconds", type=int, default=120)
    args = parser.parse_args()
    try:
        payload = _run(args)
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}:{exc}"}), file=sys.stderr)
        return 1
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
