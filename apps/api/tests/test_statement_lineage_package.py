from __future__ import annotations

from types import SimpleNamespace

from app.domain.platform import StatementStatus
from app.services.statements import _linear_statement_lineage


def _row(
    statement_id: str,
    statement_type: str,
    digest: str,
    *,
    previous=None,
):
    return SimpleNamespace(
        id=statement_id,
        statement_type=statement_type,
        payload_digest_sha256=digest,
        previous_statement_id=previous.id if previous else None,
        payload={
            "previous_payload_digest_sha256": (previous.payload_digest_sha256 if previous else None)
        },
    )


def test_multi_step_status_lineage_derives_status_from_the_signed_tip():
    root = _row("stm_root", "RESULT", "11" * 32)
    dispute = _row("stm_dispute", "DISPUTE", "22" * 32, previous=root)
    revocation = _row("stm_revocation", "REVOCATION", "33" * 32, previous=dispute)

    lineage, status = _linear_statement_lineage(
        root,
        # Deliberately unordered: lineage follows signed predecessor links, not
        # mutable row status or caller-controlled array order.
        [revocation, root, dispute],
    )

    assert [row.id for row in lineage] == ["stm_root", "stm_dispute", "stm_revocation"]
    assert status == StatementStatus.REVOKED
