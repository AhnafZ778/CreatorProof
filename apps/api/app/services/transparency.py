"""Durable RFC 6962-style transparency log.

Leaves and checkpoints live in the database rather than a process-local JSONL
file, so a restart, a second worker or a container rebuild cannot fork the log.
This is auditable append-only infrastructure and is never described as a
blockchain; an optional external commitment of a checkpoint root is separate.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

logger = logging.getLogger("creatorproof.transparency")

_write_lock = threading.Lock()


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def leaf_hash(packet_hash: str) -> bytes:
    return hashlib.sha256(b"\x00" + bytes.fromhex(packet_hash)).digest()


def node_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def _root_and_proof(leaves: list[bytes], index: int) -> tuple[bytes, list[dict]]:
    if not leaves or not 0 <= index < len(leaves):
        raise ValueError("Invalid Merkle leaf index")
    level = list(leaves)
    cursor = index
    proof: list[dict] = []
    while len(level) > 1:
        if cursor % 2 == 0 and cursor + 1 < len(level):
            proof.append({"side": "right", "hash": level[cursor + 1].hex()})
        elif cursor % 2 == 1:
            proof.append({"side": "left", "hash": level[cursor - 1].hex()})
        level = [
            node_hash(level[offset], level[offset + 1])
            if offset + 1 < len(level)
            else level[offset]
            for offset in range(0, len(level), 2)
        ]
        cursor //= 2
    return level[0], proof


def compute_root(leaves: list[bytes]) -> bytes:
    if not leaves:
        return b"\x00" * 32
    level = list(leaves)
    while len(level) > 1:
        level = [
            node_hash(level[offset], level[offset + 1])
            if offset + 1 < len(level)
            else level[offset]
            for offset in range(0, len(level), 2)
        ]
    return level[0]


def verify_inclusion(packet_hash: str, root_hex: str, proof: list[dict]) -> bool:
    try:
        value = leaf_hash(packet_hash)
        for item in proof:
            if item["side"] not in {"left", "right"}:
                return False
            sibling = bytes.fromhex(str(item["hash"]))
            value = (
                node_hash(sibling, value) if item["side"] == "left" else node_hash(value, sibling)
            )
        return value == bytes.fromhex(root_hex)
    except (KeyError, TypeError, ValueError):
        return False


class TransparencyLog:
    """Append-only log of statement/packet commitments with signed checkpoints."""

    def __init__(self, *, log_id: str, signer, checkpoint_interval: int = 1) -> None:
        self.log_id = log_id
        self.signer = signer
        self.checkpoint_interval = max(1, checkpoint_interval)

    verify_inclusion = staticmethod(verify_inclusion)

    def _leaf_hashes(self, db: Session) -> list[bytes]:
        from app.models import TransparencyLeaf

        rows = db.scalars(
            select(TransparencyLeaf)
            .where(TransparencyLeaf.log_id == self.log_id)
            .order_by(TransparencyLeaf.leaf_index)
        ).all()
        return [bytes.fromhex(row.leaf_hash_sha256) for row in rows]

    def _acquire_database_write_lock(self, db: Session) -> None:
        """Serialize one log head across every PostgreSQL process.

        The in-process lock protects SQLite threads. PostgreSQL deployments can
        have many API/worker processes, so the transaction also owns a stable
        advisory lock until the leaf and its checkpoint commit together.
        """
        if db.get_bind().dialect.name != "postgresql":
            return
        lock_key = int.from_bytes(
            hashlib.sha256(f"creatorproof:transparency:{self.log_id}".encode()).digest()[:8],
            byteorder="big",
            signed=True,
        )
        db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})

    def _checkpoint_covering(
        self,
        db: Session,
        *,
        minimum_tree_size: int,
        maximum_tree_size: int,
    ):
        from app.models import TransparencyCheckpoint

        return db.scalar(
            select(TransparencyCheckpoint)
            .where(
                TransparencyCheckpoint.log_id == self.log_id,
                TransparencyCheckpoint.tree_size >= minimum_tree_size,
                TransparencyCheckpoint.tree_size <= maximum_tree_size,
            )
            .order_by(TransparencyCheckpoint.tree_size.desc())
            .limit(1)
        )

    @staticmethod
    def _checkpoint_payload(checkpoint) -> dict | None:
        if checkpoint is None:
            return None
        payload = {
            "tree_size": checkpoint.tree_size,
            "root_sha256": checkpoint.root_sha256,
            "signature_kid": checkpoint.signature_kid,
            "signature_b64": checkpoint.signature_b64,
        }
        if checkpoint.external_commitment is not None:
            payload["external_commitment"] = checkpoint.external_commitment
        return payload

    def _receipt_for_leaf(self, db: Session, *, leaf, packet_hash: str) -> dict:
        if leaf.packet_hash_sha256.lower() != packet_hash:
            raise ValueError("statement_id is already bound to a different packet hash")
        leaves = self._leaf_hashes(db)
        checkpoint = self._checkpoint_covering(
            db,
            minimum_tree_size=leaf.leaf_index + 1,
            maximum_tree_size=len(leaves),
        )
        tree_size = checkpoint.tree_size if checkpoint is not None else len(leaves)
        root, proof = _root_and_proof(leaves[:tree_size], leaf.leaf_index)
        if checkpoint is not None and checkpoint.root_sha256 != root.hex():
            raise RuntimeError("stored transparency checkpoint root mismatch")
        return {
            "schema": "creatorproof.transparency_receipt.v2",
            "log_id": self.log_id,
            "leaf_index": leaf.leaf_index,
            "packet_hash_sha256": packet_hash,
            "leaf_hash_sha256": leaf.leaf_hash_sha256,
            "tree_size": tree_size,
            "root_sha256": root.hex(),
            "inclusion_proof": proof,
            "inclusion_verified": verify_inclusion(packet_hash, root.hex(), proof),
            "checkpoint": self._checkpoint_payload(checkpoint),
            "anchor_scope": "LOCAL_APPEND_ONLY_LOG_NOT_BLOCKCHAIN",
        }

    def append(self, db: Session, *, packet_hash: str, statement_id: str | None = None) -> dict:
        """Idempotently append one commitment under an atomically signed head."""
        from app.models import TransparencyLeaf

        if len(packet_hash) != 64:
            raise ValueError("packet hash must be a 32-byte hex digest")
        bytes.fromhex(packet_hash)
        packet_hash = packet_hash.lower()

        with _write_lock:
            # A SQLite process cannot take a PostgreSQL-style advisory lock. Its
            # unique indexes turn a rare cross-process collision into a safe retry.
            for attempt in range(8):
                try:
                    self._acquire_database_write_lock(db)
                    if statement_id is not None:
                        existing = db.scalar(
                            select(TransparencyLeaf).where(
                                TransparencyLeaf.log_id == self.log_id,
                                TransparencyLeaf.statement_id == statement_id,
                            )
                        )
                        if existing is not None:
                            receipt = self._receipt_for_leaf(
                                db,
                                leaf=existing,
                                packet_hash=packet_hash,
                            )
                            db.commit()
                            return receipt

                    current_max = db.scalar(
                        select(func.max(TransparencyLeaf.leaf_index)).where(
                            TransparencyLeaf.log_id == self.log_id
                        )
                    )
                    next_index = 0 if current_max is None else int(current_max) + 1
                    digest = leaf_hash(packet_hash)
                    leaf = TransparencyLeaf(
                        log_id=self.log_id,
                        leaf_index=next_index,
                        statement_id=statement_id,
                        packet_hash_sha256=packet_hash,
                        leaf_hash_sha256=digest.hex(),
                    )
                    db.add(leaf)
                    # The session factory disables autoflush. Flush explicitly so
                    # the root includes this leaf before the same transaction signs it.
                    db.flush()

                    leaves = self._leaf_hashes(db)
                    root, proof = _root_and_proof(leaves, next_index)
                    tree_size = len(leaves)
                    checkpoint = None
                    if tree_size % self.checkpoint_interval == 0:
                        checkpoint = self._write_checkpoint(
                            db,
                            tree_size=tree_size,
                            root=root,
                        )
                    db.commit()
                    return {
                        "schema": "creatorproof.transparency_receipt.v2",
                        "log_id": self.log_id,
                        "leaf_index": next_index,
                        "packet_hash_sha256": packet_hash,
                        "leaf_hash_sha256": digest.hex(),
                        "tree_size": tree_size,
                        "root_sha256": root.hex(),
                        "inclusion_proof": proof,
                        "inclusion_verified": verify_inclusion(
                            packet_hash,
                            root.hex(),
                            proof,
                        ),
                        "checkpoint": checkpoint,
                        "anchor_scope": "LOCAL_APPEND_ONLY_LOG_NOT_BLOCKCHAIN",
                    }
                except IntegrityError:
                    db.rollback()
                    if attempt == 7:
                        raise
                    # Another SQLite process may have committed the same statement
                    # or claimed the next leaf index. Re-read under a fresh transaction.
                    continue

        raise RuntimeError("transparency append retry budget exhausted")  # pragma: no cover

    def _write_checkpoint(self, db: Session, *, tree_size: int, root: bytes) -> dict:
        from app.models import TransparencyCheckpoint

        existing = db.scalar(
            select(TransparencyCheckpoint).where(
                TransparencyCheckpoint.log_id == self.log_id,
                TransparencyCheckpoint.tree_size == tree_size,
            )
        )
        if existing is not None:
            if existing.root_sha256 != root.hex():
                raise RuntimeError("stored transparency checkpoint root mismatch")
            return {
                "tree_size": existing.tree_size,
                "root_sha256": existing.root_sha256,
                "signature_kid": existing.signature_kid,
                "signature_b64": existing.signature_b64,
            }
        body = {
            "log_id": self.log_id,
            "tree_size": tree_size,
            "root_sha256": root.hex(),
        }
        signed = self.signer.sign(body)
        row = TransparencyCheckpoint(
            log_id=self.log_id,
            tree_size=tree_size,
            root_sha256=root.hex(),
            signature_kid=signed["signature_kid"],
            signature_b64=signed["signature_b64"],
        )
        db.add(row)
        db.flush()
        return {
            "tree_size": tree_size,
            "root_sha256": root.hex(),
            "signature_kid": signed["signature_kid"],
            "signature_b64": signed["signature_b64"],
        }

    def flush_due_checkpoint(
        self,
        db: Session,
        *,
        max_age_seconds: float,
        now: datetime | None = None,
    ) -> dict | None:
        """Sign a trailing partial batch once its oldest leaf reaches the deadline.

        Interval-only checkpointing has a liveness hole: if traffic stops at
        ``N % checkpoint_interval != 0``, those leaves otherwise remain locally
        signed but never eligible for a public checkpoint anchor. This method is
        called by the durable dispatcher, so the deadline is restart-safe.
        """
        from app.models import TransparencyCheckpoint, TransparencyLeaf

        resolved_now = now or datetime.now(UTC)
        with _write_lock:
            self._acquire_database_write_lock(db)
            leaves = self._leaf_hashes(db)
            if not leaves:
                db.rollback()
                return None
            latest_size = int(
                db.scalar(
                    select(func.max(TransparencyCheckpoint.tree_size)).where(
                        TransparencyCheckpoint.log_id == self.log_id
                    )
                )
                or 0
            )
            if latest_size > len(leaves):
                db.rollback()
                raise RuntimeError("stored transparency checkpoint is ahead of log")
            if latest_size == len(leaves):
                db.rollback()
                return None
            oldest_uncheckpointed = db.scalar(
                select(TransparencyLeaf.created_at)
                .where(
                    TransparencyLeaf.log_id == self.log_id,
                    TransparencyLeaf.leaf_index >= latest_size,
                )
                .order_by(TransparencyLeaf.leaf_index)
                .limit(1)
            )
            if oldest_uncheckpointed is None:
                db.rollback()
                raise RuntimeError("transparency log head is not contiguous")
            deadline = _as_utc(oldest_uncheckpointed) + timedelta(seconds=max_age_seconds)
            if _as_utc(resolved_now) < deadline:
                db.rollback()
                return None

            tree_size = len(leaves)
            root = compute_root(leaves)
            try:
                checkpoint = self._write_checkpoint(db, tree_size=tree_size, root=root)
                db.commit()
                return checkpoint
            except IntegrityError:
                # A second SQLite process may have won the unique tree-size race.
                db.rollback()
                existing = db.scalar(
                    select(TransparencyCheckpoint).where(
                        TransparencyCheckpoint.log_id == self.log_id,
                        TransparencyCheckpoint.tree_size == tree_size,
                    )
                )
                if existing is None or existing.root_sha256 != root.hex():
                    raise
                return self._checkpoint_payload(existing)

    def attach_external_commitment(
        self,
        db: Session,
        *,
        tree_size: int,
        root_sha256: str,
        external_commitment: dict,
    ) -> None:
        """Attach one immutable public receipt to its exact signed checkpoint.

        The signed tree head never changes. Its external receipt is a write-once
        completion field so exported inclusion packages remain useful without a
        join to the mutable transaction work queue.
        """
        from app.models import TransparencyCheckpoint

        checkpoint = db.scalar(
            select(TransparencyCheckpoint).where(
                TransparencyCheckpoint.log_id == self.log_id,
                TransparencyCheckpoint.tree_size == int(tree_size),
            )
        )
        if checkpoint is None:
            raise LookupError("confirmed blockchain job references an unknown checkpoint")
        if checkpoint.root_sha256 != root_sha256:
            raise RuntimeError("confirmed blockchain job does not match checkpoint root")
        if checkpoint.external_commitment is not None:
            if checkpoint.external_commitment != external_commitment:
                raise RuntimeError("checkpoint external commitment is immutable")
            return
        checkpoint.external_commitment = external_commitment

    def inclusion_proof(
        self, db: Session, *, leaf_index: int, tree_size: int | None = None
    ) -> dict | None:
        """Recompute inclusion against the current head or a historical checkpoint."""
        leaves = self._leaf_hashes(db)
        resolved_size = len(leaves) if tree_size is None else int(tree_size)
        if (
            not leaves
            or resolved_size < 1
            or resolved_size > len(leaves)
            or not 0 <= leaf_index < resolved_size
        ):
            return None
        root, proof = _root_and_proof(leaves[:resolved_size], leaf_index)
        return {
            "leaf_index": leaf_index,
            "tree_size": resolved_size,
            "root_sha256": root.hex(),
            "inclusion_proof": proof,
        }

    def latest_checkpoint(self, db: Session) -> dict | None:
        from app.models import TransparencyCheckpoint

        row = db.scalar(
            select(TransparencyCheckpoint)
            .where(TransparencyCheckpoint.log_id == self.log_id)
            .order_by(TransparencyCheckpoint.tree_size.desc())
            .limit(1)
        )
        if row is None:
            return None
        return {
            "tree_size": row.tree_size,
            "root_sha256": row.root_sha256,
            "signature_kid": row.signature_kid,
            "signature_b64": row.signature_b64,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "external_commitment": row.external_commitment,
        }

    def check_consistency(self, db: Session) -> dict:
        """Detect index gaps, leaf tampering, bad signatures and root equivocation."""
        from app.models import SigningKey, TransparencyCheckpoint, TransparencyLeaf
        from app.services.signing import verify_statement_signature

        leaf_rows = db.scalars(
            select(TransparencyLeaf)
            .where(TransparencyLeaf.log_id == self.log_id)
            .order_by(TransparencyLeaf.leaf_index)
        ).all()
        mismatches: list[dict] = []
        leaves: list[bytes] = []
        for expected_index, row in enumerate(leaf_rows):
            if row.leaf_index != expected_index:
                mismatches.append(
                    {
                        "tree_size": len(leaf_rows),
                        "leaf_index": row.leaf_index,
                        "expected_leaf_index": expected_index,
                        "reason": "LEAF_INDEX_GAP",
                    }
                )
            try:
                recomputed_leaf = leaf_hash(row.packet_hash_sha256)
            except (TypeError, ValueError):
                recomputed_leaf = b"\x00" * 32
                mismatches.append(
                    {
                        "tree_size": len(leaf_rows),
                        "leaf_index": row.leaf_index,
                        "reason": "INVALID_PACKET_DIGEST",
                    }
                )
            if row.leaf_hash_sha256 != recomputed_leaf.hex():
                mismatches.append(
                    {
                        "tree_size": len(leaf_rows),
                        "leaf_index": row.leaf_index,
                        "reason": "LEAF_HASH_MISMATCH",
                        "recorded_leaf_hash": row.leaf_hash_sha256,
                        "recomputed_leaf_hash": recomputed_leaf.hex(),
                    }
                )
            # Roots are recomputed from the committed packet digests, not from a
            # potentially tampered leaf_hash_sha256 column.
            leaves.append(recomputed_leaf)

        checkpoints = db.scalars(
            select(TransparencyCheckpoint)
            .where(TransparencyCheckpoint.log_id == self.log_id)
            .order_by(TransparencyCheckpoint.tree_size)
        ).all()
        signing_keys = {key.kid: key for key in db.scalars(select(SigningKey)).all() if key.kid}
        for checkpoint in checkpoints:
            if checkpoint.tree_size < 1:
                mismatches.append(
                    {"tree_size": checkpoint.tree_size, "reason": "INVALID_TREE_SIZE"}
                )
                continue
            if checkpoint.tree_size > len(leaves):
                mismatches.append(
                    {"tree_size": checkpoint.tree_size, "reason": "CHECKPOINT_AHEAD_OF_LOG"}
                )
                continue
            recomputed = compute_root(leaves[: checkpoint.tree_size]).hex()
            if recomputed != checkpoint.root_sha256:
                mismatches.append(
                    {
                        "tree_size": checkpoint.tree_size,
                        "reason": "ROOT_MISMATCH",
                        "recorded_root": checkpoint.root_sha256,
                        "recomputed_root": recomputed,
                    }
                )
            signing_key = signing_keys.get(checkpoint.signature_kid)
            checkpoint_payload = {
                "log_id": checkpoint.log_id,
                "tree_size": checkpoint.tree_size,
                "root_sha256": checkpoint.root_sha256,
            }
            if signing_key is None:
                mismatches.append(
                    {"tree_size": checkpoint.tree_size, "reason": "UNKNOWN_CHECKPOINT_KEY"}
                )
            elif not verify_statement_signature(
                checkpoint_payload,
                signature_b64=checkpoint.signature_b64,
                public_key_hex=signing_key.public_key_hex,
            ):
                mismatches.append(
                    {"tree_size": checkpoint.tree_size, "reason": "INVALID_CHECKPOINT_SIGNATURE"}
                )
        return {
            "log_id": self.log_id,
            "tree_size": len(leaves),
            "checkpoints_checked": len(checkpoints),
            "consistent": not mismatches,
            "mismatches": mismatches,
        }
