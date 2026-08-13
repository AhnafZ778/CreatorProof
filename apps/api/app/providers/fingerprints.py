from hashlib import sha256

import imagehash
from PIL import Image

from app.providers.contracts import Fingerprints


class BaselineFingerprintProvider:
    """Production-safe baseline: cryptographic SHA-256 + DCT perceptual hash.

    The perceptual hash here is intentionally *not* labeled PDQ. PDQ is a separate
    algorithm and should only be exposed once its real implementation is integrated.
    """

    name = "sha256+phash-v1"

    def compute(self, raw: bytes, image: Image.Image) -> Fingerprints:
        return Fingerprints(
            sha256=sha256(raw).hexdigest(),
            phash=str(imagehash.phash(image.convert("RGB"), hash_size=8)),
        )


def phash_distance(left: str, right: str) -> int:
    return int(imagehash.hex_to_hash(left) - imagehash.hex_to_hash(right))
