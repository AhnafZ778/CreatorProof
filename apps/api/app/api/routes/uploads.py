from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_container, require_any_scope
from app.container import Container
from app.core.security import AuthContext
from app.domain.platform import CredentialScope
from app.models import new_id
from app.schemas import DirectUploadCreatedRead, DirectUploadCreateRequest
from app.services.upload_tokens import issue_upload_token

router = APIRouter(prefix="/v1/uploads", tags=["uploads"])


@router.post("", response_model=DirectUploadCreatedRead, status_code=status.HTTP_201_CREATED)
def create_direct_upload(
    payload: DirectUploadCreateRequest,
    auth: Annotated[
        AuthContext,
        Depends(
            require_any_scope(
                CredentialScope.SCANS_WRITE,
                CredentialScope.WORKS_WRITE,
            )
        ),
    ],
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    """Issue a tenant-bound request that uploads bytes straight to private storage."""

    required_scope = (
        CredentialScope.SCANS_WRITE if payload.purpose == "scan" else CredentialScope.WORKS_WRITE
    )
    if not auth.has_scope(required_scope):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "INSUFFICIENT_SCOPE",
                "message": f"This credential lacks the '{required_scope.value}' permission.",
                "required_scope": required_scope.value,
            },
        )
    if any(character in payload.filename for character in ("\x00", "/", "\\")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "UPLOAD_FILENAME_INVALID", "message": "Use a plain file name."},
        )
    if payload.size_bytes > container.settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "code": "UPLOAD_TOO_LARGE",
                "message": "The image exceeds this deployment's upload limit.",
                "max_bytes": container.settings.max_upload_bytes,
            },
        )

    upload_id = new_id("upl")
    object_key = f"incoming/{auth.tenant_id}/{payload.purpose}/{upload_id}/source.bin"
    upload_token, claims = issue_upload_token(
        container.settings.upload_token_secret,
        tenant_id=auth.tenant_id,
        purpose=payload.purpose,
        key=object_key,
        filename=payload.filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        ttl_seconds=container.settings.upload_token_ttl_seconds,
    )
    instruction = container.storage.presign_put(
        object_key,
        content_type=payload.content_type,
        expires_seconds=container.settings.upload_token_ttl_seconds,
        max_bytes=payload.size_bytes,
        metadata={
            "creatorproof-purpose": payload.purpose,
            "creatorproof-tenant": auth.tenant_id,
            "creatorproof-upload-nonce": claims.nonce,
            "creatorproof-size-bytes": str(payload.size_bytes),
        },
    )
    if instruction is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "DIRECT_UPLOAD_UNAVAILABLE",
                "message": "Direct upload requires the configured S3-compatible object store.",
            },
        )
    instruction["max_bytes"] = payload.size_bytes
    return {"upload_token": upload_token, "upload": instruction}
