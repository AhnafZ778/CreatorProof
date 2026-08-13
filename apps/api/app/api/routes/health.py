from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import text

from app import __build_signature__, __version__
from app.schemas import HealthRead

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthRead)
def healthz(request: Request) -> HealthRead:
    container = request.app.state.container
    ai = container.ai_retrieval.status()
    style = container.style_retrieval.status()
    synthetic = container.synthetic_detection.status()
    visible_marker = container.visible_markers.status()
    provenance = container.provenance.status()
    proof = container.proof_anchor.status()
    return HealthRead(
        status="ok",
        version=__version__,
        build_signature=__build_signature__,
        job_backend=container.queue.name,
        ai_provider=ai["provider"],
        ai_available=ai["available"],
        ai_device=ai["device"],
        ai_reason=ai["reason"],
        style_provider=style["provider"],
        style_available=style["available"],
        style_learned=style["learned"],
        style_device=style["device"],
        style_reason=style["reason"],
        synthetic_provider=synthetic["provider"],
        synthetic_available=synthetic["available"],
        synthetic_detectors=synthetic["active_detectors"],
        synthetic_evidence_families=synthetic["active_evidence_families"],
        synthetic_batched_detectors=synthetic["batched_detectors"],
        synthetic_reason=(
            synthetic["configuration_warning"]
            or (
                synthetic["unavailable_detectors"][0]["reason"]
                if synthetic["unavailable_detectors"]
                else None
            )
        ),
        visible_marker_provider=visible_marker["provider"],
        visible_marker_available=visible_marker["available"],
        visible_marker_reason=visible_marker["reason"],
        provenance_provider=provenance["provider"],
        provenance_available=provenance["available"],
        proof_provider=proof["provider"],
        proof_available=proof["available"],
        proof_scope=proof["scope"],
        origin_policy_mode=container.settings.synthetic_policy_mode,
        copy_retrieval_requirement=container.settings.copy_retrieval_requirement,
    )


@router.get("/readyz", response_model=HealthRead)
def readyz(request: Request) -> HealthRead:
    container = request.app.state.container
    db = container.database.session_factory()
    try:
        db.execute(text("SELECT 1"))
        if not container.queue.healthy():
            raise RuntimeError("queue unavailable")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dependency not ready",
        ) from exc
    finally:
        db.close()
    ai = container.ai_retrieval.status()
    style = container.style_retrieval.status()
    synthetic = container.synthetic_detection.status()
    visible_marker = container.visible_markers.status()
    provenance = container.provenance.status()
    proof = container.proof_anchor.status()
    return HealthRead(
        status="ready",
        version=__version__,
        build_signature=__build_signature__,
        job_backend=container.queue.name,
        ai_provider=ai["provider"],
        ai_available=ai["available"],
        ai_device=ai["device"],
        ai_reason=ai["reason"],
        style_provider=style["provider"],
        style_available=style["available"],
        style_learned=style["learned"],
        style_device=style["device"],
        style_reason=style["reason"],
        synthetic_provider=synthetic["provider"],
        synthetic_available=synthetic["available"],
        synthetic_detectors=synthetic["active_detectors"],
        synthetic_evidence_families=synthetic["active_evidence_families"],
        synthetic_batched_detectors=synthetic["batched_detectors"],
        synthetic_reason=(
            synthetic["configuration_warning"]
            or (
                synthetic["unavailable_detectors"][0]["reason"]
                if synthetic["unavailable_detectors"]
                else None
            )
        ),
        visible_marker_provider=visible_marker["provider"],
        visible_marker_available=visible_marker["available"],
        visible_marker_reason=visible_marker["reason"],
        provenance_provider=provenance["provider"],
        provenance_available=provenance["available"],
        proof_provider=proof["provider"],
        proof_available=proof["available"],
        proof_scope=proof["scope"],
        origin_policy_mode=container.settings.synthetic_policy_mode,
        copy_retrieval_requirement=container.settings.copy_retrieval_requirement,
    )
