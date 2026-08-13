from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.providers.proof import verify_merkle_receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a CreatorProof local Merkle receipt.")
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.receipt.read_text(encoding="utf-8"))
    receipt = payload.get("receipt", payload)
    valid = verify_merkle_receipt(
        str(receipt["packet_hash_sha256"]),
        str(receipt["root_sha256"]),
        list(receipt["inclusion_proof"]),
    )
    print(
        json.dumps(
            {
                "valid": valid,
                "scope": receipt.get("anchor_scope"),
                "warning": "A local Merkle receipt is not a public blockchain transaction.",
            },
            indent=2,
        )
    )
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
