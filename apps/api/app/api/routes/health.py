from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import func, select, text

from app import __build_signature__, __version__
from app.observability import METRICS
from app.schemas import HealthRead

router = APIRouter(tags=["health"])


def _degraded_capabilities(snapshot: dict) -> list[str]:
    """Name every capability a caller should not assume is running.

    Optional providers degrade honestly instead of silently disappearing.
    """
    degraded: list[str] = []
    if not snapshot["ai"]["available"]:
        degraded.append("COPY_LEARNED_RETRIEVAL_UNAVAILABLE")
    if not snapshot["style"]["available"]:
        degraded.append("CREATOR_PROFILE_UNAVAILABLE")
    elif not snapshot["style"]["learned"]:
        degraded.append("CREATOR_PROFILE_DIAGNOSTIC_ONLY")
    if not snapshot["synthetic"]["available"]:
        degraded.append("AI_ORIGIN_DETECTION_UNAVAILABLE")
    if not snapshot["visible_marker"]["available"]:
        degraded.append("VISIBLE_LABEL_OCR_UNAVAILABLE")
    if not snapshot["provenance"]["available"]:
        degraded.append("C2PA_PROVENANCE_UNAVAILABLE")
    if not snapshot["proof"].get("available"):
        degraded.append("PROOF_ANCHOR_UNAVAILABLE")
    elif snapshot["proof"].get("scope") == "LOCAL_TRANSPARENCY_LOG":
        degraded.append("PROOF_IS_LOCAL_TRANSPARENCY_LOG_NOT_BLOCKCHAIN")
    if not snapshot["signing"]["enabled"]:
        degraded.append("EVIDENCE_STATEMENT_SIGNING_DISABLED")
    elif snapshot["signing"]["key_source"] == "DERIVED_DEVELOPMENT_KEY":
        degraded.append("SIGNING_USES_DERIVED_DEVELOPMENT_KEY")
    if snapshot["dev_auth_enabled"]:
        degraded.append("DEVELOPMENT_API_KEY_ENABLED_NOT_A_PRODUCTION_BOUNDARY")
    blockchain_states = snapshot["blockchain"].get("states") or {}
    if snapshot["blockchain"].get("chain_writes_configured") and not snapshot["blockchain"].get(
        "chain_writes_ready"
    ):
        degraded.append("BLOCKCHAIN_CONFIGURED_BUT_NOT_LIVE_WRITE_READY")
    if blockchain_states.get("FAILED", 0):
        degraded.append("BLOCKCHAIN_ANCHOR_JOBS_FAILED")
    return degraded


def _snapshot(request: Request) -> dict:
    container = request.app.state.container
    queue_stats: dict = {}
    try:
        queue_stats = container.queue.stats() if container.queue is not None else {}
    except Exception:
        queue_stats = {}
    tree_size = None
    outbox_pending = None
    try:
        from app.models import OutboxEvent, TransparencyLeaf

        db = container.database.session_factory()
        try:
            tree_size = int(
                db.scalar(
                    select(func.count(TransparencyLeaf.id)).where(
                        TransparencyLeaf.log_id == container.transparency.log_id
                    )
                )
                or 0
            )
            outbox_pending = int(
                db.scalar(select(func.count(OutboxEvent.id)).where(OutboxEvent.state == "PENDING"))
                or 0
            )
        finally:
            db.close()
    except Exception:
        tree_size = None
    return {
        "container": container,
        "model_bundle": container.model_bundle.status(),
        "style_profiles": container.style_profiles.status(),
        "ai": container.ai_retrieval.status(),
        "style": container.style_retrieval.status(),
        "synthetic": container.synthetic_detection.status(),
        "visible_marker": container.visible_markers.status(),
        "provenance": container.provenance.status(),
        "proof": container.proof_anchor.status(),
        "blockchain": container.blockchain.status(),
        "signing": container.signer.status(),
        "storage": container.storage.status(),
        "queue": queue_stats,
        "tree_size": tree_size,
        "outbox_pending": outbox_pending,
        "dev_auth_enabled": container.settings.dev_auth_enabled,
    }


def _build(request: Request, status_label: str) -> HealthRead:
    snapshot = _snapshot(request)
    container = snapshot["container"]
    synthetic = snapshot["synthetic"]
    proof = snapshot["proof"]
    signing = snapshot["signing"]
    queue = snapshot["queue"]
    model_bundle = snapshot["model_bundle"]
    model_runtime = container.model_bundle_runtime
    style_profiles = snapshot["style_profiles"]
    synthetic_routing = synthetic.get("routing") or {}
    return HealthRead(
        status=status_label,
        version=__version__,
        build_signature=__build_signature__,
        job_backend=container.queue.name,
        model_bundle_id=model_bundle["bundle_id"],
        model_bundle_manifest_state=model_bundle["manifest_state"],
        model_bundle_qualification_state=model_bundle["qualification_state"],
        model_bundle_manifest_digest=model_bundle["manifest_digest_sha256"],
        model_bundle_reason_codes=model_bundle["reason_codes"],
        model_bundle_declared_state_verified=model_runtime[
            "runtime_requirement_met_for_declared_state"
        ],
        model_bundle_demo_ready=model_runtime["demo_ready"],
        model_bundle_runtime_artifact_failures=model_runtime["runtime_artifact_failures"],
        model_bundle_application_revision_matches=model_runtime["application_revision"]["matches"],
        model_bundle_runtime_environment_matches=model_runtime["runtime_environment"]["matches"],
        ai_provider=snapshot["ai"]["provider"],
        ai_available=snapshot["ai"]["available"],
        ai_device=snapshot["ai"]["device"],
        ai_reason=snapshot["ai"]["reason"],
        style_provider=snapshot["style"]["provider"],
        style_available=snapshot["style"]["available"],
        style_learned=snapshot["style"]["learned"],
        style_device=snapshot["style"]["device"],
        style_reason=snapshot["style"]["reason"],
        style_profile_manifest_state=style_profiles["state"],
        style_profile_manifest_id=style_profiles["manifest_id"],
        style_profile_count=style_profiles["profile_count"],
        style_authorized_profile_count=style_profiles["authorized_profile_count"],
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
        synthetic_calibration_state=synthetic["calibration"]["state"],
        synthetic_routing=synthetic_routing,
        synthetic_primary_provider=synthetic_routing.get("primary_provider"),
        synthetic_primary_state=synthetic_routing.get("primary_state"),
        synthetic_local_fallback_available=bool(synthetic_routing.get("local_fallback_available")),
        visible_marker_provider=snapshot["visible_marker"]["provider"],
        visible_marker_available=snapshot["visible_marker"]["available"],
        visible_marker_reason=snapshot["visible_marker"]["reason"],
        provenance_provider=snapshot["provenance"]["provider"],
        provenance_available=snapshot["provenance"]["available"],
        provenance_trust_policy_id=snapshot["provenance"].get("trust_policy_id"),
        proof_provider=proof["provider"],
        proof_available=proof["available"],
        proof_scope=proof["scope"],
        proof_network_label=proof.get("network_label"),
        proof_chain_id=proof.get("chain_id"),
        proof_contract_address=proof.get("contract_address"),
        proof_schema_uid=proof.get("schema_uid"),
        proof_attester_address=proof.get("attester_address"),
        proof_requires_chain=container.settings.proof_require_chain,
        blockchain_deployment_id=snapshot["blockchain"].get("deployment_id"),
        blockchain_anchor_states=snapshot["blockchain"].get("states") or {},
        blockchain_oldest_pending_at=snapshot["blockchain"].get("oldest_pending_at"),
        signing_enabled=bool(signing["enabled"]),
        signing_kid=signing["kid"],
        signing_algorithm=signing["algorithm"],
        signing_key_source=signing["key_source"],
        transparency_log_id=container.transparency.log_id,
        transparency_tree_size=snapshot["tree_size"],
        queue_transport=queue.get("transport"),
        queue_depth=queue.get("depth"),
        queue_pending=queue.get("pending"),
        queue_dead_letter=queue.get("dead_letter"),
        outbox_pending=snapshot["outbox_pending"],
        storage_provider=snapshot["storage"]["provider"],
        dev_auth_enabled=snapshot["dev_auth_enabled"],
        degraded_capabilities=_degraded_capabilities(snapshot),
        origin_policy_mode=container.settings.synthetic_policy_mode,
        copy_retrieval_requirement=container.settings.copy_retrieval_requirement,
        copy_exhaustive_verification_max_entries=(
            container.settings.copy_exhaustive_verification_max_entries
        ),
    )


@router.get("/healthz", response_model=HealthRead)
def healthz(request: Request) -> HealthRead:
    return _build(request, "ok")


@router.get("/readyz", response_model=HealthRead)
def readyz(request: Request) -> HealthRead:
    """Dependency readiness. Optional model providers never block readiness."""
    container = request.app.state.container
    db = container.database.session_factory()
    failures: list[str] = []
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        failures.append("DATABASE_UNAVAILABLE")
    finally:
        db.close()
    try:
        if not container.queue.healthy():
            failures.append("QUEUE_UNAVAILABLE")
    except Exception:
        failures.append("QUEUE_UNAVAILABLE")
    if container.settings.proof_require_chain:
        anchor = container.proof_anchor
        if not hasattr(anchor, "preflight"):
            failures.append("CHAIN_PROVIDER_NOT_CONFIGURED")
        else:
            try:
                preflight = anchor.preflight()
                if not preflight.get("ready"):
                    failures.append(str(preflight.get("reason") or "CHAIN_PREFLIGHT_FAILED"))
            except Exception:
                failures.append("CHAIN_PREFLIGHT_FAILED")
    if failures:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DEPENDENCY_NOT_READY", "failures": failures},
        )
    return _build(request, "ready")


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    """Prometheus exposition of request, queue, stage, proof and webhook counters."""
    container = request.app.state.container
    if not container.settings.metrics_enabled:
        raise HTTPException(status_code=404, detail="Metrics are disabled")
    try:
        stats = container.queue.stats() if container.queue is not None else {}
        METRICS.set_gauge("creatorproof_queue_depth", float(stats.get("depth", 0) or 0))
        METRICS.set_gauge("creatorproof_queue_pending", float(stats.get("pending", 0) or 0))
        METRICS.set_gauge("creatorproof_queue_dead_letter", float(stats.get("dead_letter", 0) or 0))
        blockchain = container.blockchain.status()
        for state, count in (blockchain.get("states") or {}).items():
            METRICS.set_gauge(
                "creatorproof_blockchain_anchor_jobs",
                float(count),
                state=str(state),
            )
    except Exception:
        pass
    return Response(content=METRICS.render_prometheus(), media_type="text/plain; version=0.0.4")
