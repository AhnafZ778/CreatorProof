# Local AI model artifacts

CreatorProof does not commit pretrained weights to the source archive.

Run `python scripts/fetch_sscd_model.py` from `apps/api` to download the official
`sscd_disc_mixup.torchscript.pt` artifact linked by Meta's SSCD repository into this
directory. The application reports an explicit `phash-fallback` provider until both the
model and PyTorch are present.

For the optional creator-style lane, run `python -m scripts.fetch_csd_runtime` after installing
`requirements-style-experimental.txt`. The CSD checkpoint is stored under `models/csd-vit-l/` and
the external source checkout under `vendor/CSD/`; neither is committed to the source archive. Always
run `python -m scripts.check_style_ai --require-learned` and the style benchmark before claiming the
learned provider is active/effective.

For the optional AI-origin lane, install `requirements-synthetic.txt`, then run
`python -m scripts.fetch_community_forensics_model` and
`python -m scripts.check_synthetic_ai`. The official Community Forensics safetensors are stored under
`models/community-forensics-384/` and never committed. Runtime activation is not an accuracy claim;
fit an authorized held-out calibration file and run the generator-disjoint synthetic benchmark.

`synthetic-calibration.json` is deployment-domain state. It must identify provider/model version and
must be invalidated whenever weights, preprocessing, or target domain changes.

Do not put API keys in this directory.
