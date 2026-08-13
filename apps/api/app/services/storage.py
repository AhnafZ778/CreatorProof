"""Object storage boundary.

Keys are tenant-prefixed and S3-compatible so the local filesystem backend and a
production bucket share one layout. Deletion works on a prefix, because a
candidate's derived artifacts — thumbnails, normalized copies, alignment
visualizations, embeddings — must disappear with the original upload.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger("creatorproof.storage")


def tenant_prefix(tenant_id: str) -> str:
    return f"t/{tenant_id}"


def candidate_prefix(tenant_id: str, scan_id: str) -> str:
    return f"scans/{tenant_id}/{scan_id}"


def work_prefix(tenant_id: str, work_id: str) -> str:
    return f"works/{tenant_id}/{work_id}"


class LocalObjectStore:
    name = "local-filesystem"

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        safe = Path(key)
        if safe.is_absolute() or ".." in safe.parts:
            raise ValueError("Unsafe storage key")
        target = (self.root / safe).resolve()
        if self.root not in target.parents and target != self.root:
            raise ValueError("Unsafe storage key")
        return target

    def put(self, key: str, raw: bytes) -> str:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        )
        temporary_path = Path(temporary.name)
        try:
            with temporary:
                temporary.write(raw)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, target)
        finally:
            temporary_path.unlink(missing_ok=True)
        return str(Path(key))

    def read(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def exists(self, key: str) -> bool:
        try:
            return self._resolve(key).exists()
        except ValueError:
            return False

    def delete(self, key: str | None) -> None:
        if not key:
            return
        self._resolve(key).unlink(missing_ok=True)

    def list_prefix(self, prefix: str) -> list[str]:
        base = self._resolve(prefix)
        if not base.exists():
            return []
        if base.is_file():
            return [prefix]
        return [
            str(path.relative_to(self.root)) for path in sorted(base.rglob("*")) if path.is_file()
        ]

    def delete_prefix(self, prefix: str) -> list[str]:
        """Remove every object under ``prefix`` and return what was deleted."""
        deleted = self.list_prefix(prefix)
        base = self._resolve(prefix)
        if base.is_file():
            base.unlink(missing_ok=True)
        elif base.exists():
            shutil.rmtree(base, ignore_errors=True)
        remaining = self.list_prefix(prefix)
        if remaining:
            logger.warning("storage_prefix_partially_deleted prefix=%s", prefix)
        return [key for key in deleted if key not in set(remaining)]

    def status(self) -> dict:
        return {
            "provider": self.name,
            "root": str(self.root),
            "encrypted_at_rest": False,
            "public_access": False,
            "note": (
                "Local filesystem storage is a development backend. Production requires "
                "an S3-compatible bucket with encryption, no public access and lifecycle "
                "rules for short-lived candidate objects."
            ),
        }
