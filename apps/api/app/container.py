import hashlib
from dataclasses import dataclass, field

from app.core.config import Settings
from app.db import Base, Database, build_database
from app.models import Tenant
from app.providers.ai_retrieval import SSCDVisualEmbeddingProvider
from app.providers.aligned_perceptual import AlignedPerceptualVerifier
from app.providers.counterparty_signature import build_counterparty_verifier
from app.providers.fingerprints import BaselineFingerprintProvider
from app.providers.geometry import ORBGeometricVerifier
from app.providers.network_registry import build_member_registry
from app.providers.proof import build_proof_anchor
from app.providers.provenance import ProvenanceRouter
from app.providers.style_retrieval import StyleEmbeddingRouter
from app.providers.synthetic_detection import SyntheticDetectorRouter
from app.providers.visible_markers import VisibleAIMarkerProvider
from app.services.blockchain import BlockchainAnchorService, BlockchainDispatcherThread
from app.services.coattestation import CoAttestationService
from app.services.evidence import process_scan
from app.services.jobs import (
    InlineJobQueue,
    JobQueue,
    LocalThreadJobQueue,
    RedisJobQueue,
    RedisStreamsJobQueue,
)
from app.services.model_bundle import (
    ModelBundle,
    load_model_bundle,
    validate_model_bundle_runtime,
)
from app.services.orchestration import (
    OutboxDispatcher,
    OutboxDispatcherThread,
    StageLedger,
    StageReaperThread,
    worker_identity,
)
from app.services.policy_store import PolicyStore, ensure_default_policy
from app.services.signing import build_signer, register_signing_key
from app.services.storage import LocalObjectStore
from app.services.style_profiles import StyleProfileRegistry, load_style_profile_registry
from app.services.tenancy import bind_tenant_context
from app.services.transparency import TransparencyLog
from app.services.webhooks import WebhookDispatcher, WebhookDispatcherThread


@dataclass(slots=True)
class Container:
    settings: Settings
    model_bundle: ModelBundle
    model_bundle_runtime: dict
    database: Database
    storage: LocalObjectStore
    fingerprints: BaselineFingerprintProvider
    ai_retrieval: SSCDVisualEmbeddingProvider
    style_retrieval: StyleEmbeddingRouter
    style_profiles: StyleProfileRegistry
    geometry: ORBGeometricVerifier
    aligned_perceptual: AlignedPerceptualVerifier
    synthetic_detection: SyntheticDetectorRouter
    visible_markers: VisibleAIMarkerProvider
    provenance: ProvenanceRouter
    proof_anchor: object
    blockchain: BlockchainAnchorService | None
    signer: object
    transparency: TransparencyLog
    stage_ledger: StageLedger
    policies: PolicyStore
    # Resolved after the proof provider, which owns the RPC client they share.
    member_registry: object | None = None
    coattestations: CoAttestationService | None = None
    worker_identity: str = field(default_factory=worker_identity)
    queue: JobQueue | None = None
    outbox: OutboxDispatcher | None = None
    background_threads: list = field(default_factory=list)

    def start_background_workers(self) -> None:
        """Start outbox dispatch, lease reaping and webhook delivery.

        These are skipped for the inline test backend, where the caller drives
        execution deterministically.
        """
        if self.queue is None:
            return
        if isinstance(self.queue, InlineJobQueue):
            # Deterministic tests do not start threads. Integrity events still
            # enqueue synchronously and tests may invoke dispatch_once explicitly.
            return
        settings = self.settings
        assert self.outbox is not None
        threads = [
            OutboxDispatcherThread(self.outbox, settings.outbox_dispatch_interval_seconds),
            StageReaperThread(
                session_factory=self.database.system_session,
                ledger=self.stage_ledger,
                interval_seconds=settings.stage_reaper_interval_seconds,
            ),
            WebhookDispatcherThread(
                WebhookDispatcher(session_factory=self.database.system_session, settings=settings)
            ),
        ]
        # Redis deployments have a dedicated worker process, which owns proof
        # dispatch to avoid every API replica competing for the same signer nonce.
        if self.blockchain is not None and settings.job_backend != "redis":
            threads.append(
                BlockchainDispatcherThread(
                    self.blockchain,
                    settings.blockchain_dispatch_interval_seconds,
                )
            )
        for thread in threads:
            thread.start()
        self.background_threads = threads

    def stop_background_workers(self) -> None:
        for thread in self.background_threads:
            thread.stop()
        for thread in self.background_threads:
            thread.join(timeout=5)
        self.background_threads = []


def build_container(settings: Settings) -> Container:
    model_bundle = load_model_bundle(
        settings.model_bundle_path,
        strict=settings.model_bundle_strict,
    )
    sscd_expected_sha256 = settings.sscd_expected_sha256 or model_bundle.declared_artifact_sha256(
        "copy-retrieval-sscd"
    )
    synthetic_community_expected_sha256 = (
        settings.synthetic_community_expected_sha256
        or model_bundle.declared_artifact_sha256("origin-community-forensics")
    )
    style_expected_sha256 = (
        settings.style_csd_expected_sha256 or model_bundle.declared_artifact_sha256("style-csd")
    )
    signer = build_signer(settings)
    if settings.trusted_issuer_key_sha256:
        actual_fingerprint = hashlib.sha256(bytes.fromhex(signer.public_key_hex)).hexdigest()
        expected_fingerprint = settings.trusted_issuer_key_sha256.lower().removeprefix("sha256:")
        if actual_fingerprint != expected_fingerprint:
            raise RuntimeError(
                "Configured statement signer does not match CREATORPROOF_TRUSTED_ISSUER_KEY_SHA256"
            )
    transparency = TransparencyLog(
        log_id=settings.transparency_log_id,
        signer=signer,
        checkpoint_interval=settings.transparency_checkpoint_interval,
    )
    container = Container(
        settings=settings,
        model_bundle=model_bundle,
        model_bundle_runtime=validate_model_bundle_runtime(
            model_bundle,
            runtime_lock_path=settings.runtime_lock_path,
            artifact_paths={
                "copy-retrieval-sscd": settings.sscd_model_path,
                "origin-community-forensics": settings.synthetic_community_model_path,
                "style-csd": settings.style_csd_model_path,
            },
            include_optional_artifacts=False,
        ),
        database=build_database(settings),
        storage=LocalObjectStore(settings.storage_root),
        fingerprints=BaselineFingerprintProvider(),
        ai_retrieval=SSCDVisualEmbeddingProvider(
            settings.sscd_model_path,
            settings.sscd_device,
            expected_sha256=sscd_expected_sha256,
        ),
        style_retrieval=StyleEmbeddingRouter(
            mode=settings.style_provider,
            csd_repo_path=settings.style_csd_repo_path,
            csd_model_path=settings.style_csd_model_path,
            device=settings.style_device,
            allow_legacy_pickle=settings.style_allow_legacy_pickle,
            expected_sha256=style_expected_sha256,
            expected_repo_revision=settings.style_csd_expected_repo_revision,
        ),
        style_profiles=load_style_profile_registry(
            settings.style_profile_manifest_path,
            strict=settings.style_profile_manifest_strict,
        ),
        geometry=ORBGeometricVerifier(),
        aligned_perceptual=AlignedPerceptualVerifier(),
        synthetic_detection=SyntheticDetectorRouter(
            mode=settings.synthetic_detector,
            community_model_path=settings.synthetic_community_model_path,
            community_expected_sha256=synthetic_community_expected_sha256,
            torchscript_model_path=settings.synthetic_torchscript_model_path,
            device=settings.synthetic_device,
            external_detectors_json=settings.synthetic_external_detectors_json,
            evidence_family_registry_path=settings.synthetic_evidence_family_registry_path,
            calibration_path=settings.synthetic_calibration_path,
            min_calibration_samples=settings.synthetic_min_calibration_samples,
            min_calibration_class_samples=settings.synthetic_min_calibration_class_samples,
            external_timeout_seconds=settings.synthetic_external_timeout_seconds,
            calibration_domain_id=settings.synthetic_calibration_domain_id,
            crop_policy_id=settings.synthetic_crop_policy_id,
            model_bundle_manifest_digest=model_bundle.manifest_digest_sha256 or "",
            sightengine_api_user=settings.sightengine_api_user,
            sightengine_api_secret=settings.sightengine_api_secret,
            sightengine_timeout_seconds=settings.sightengine_timeout_seconds,
        ),
        visible_markers=VisibleAIMarkerProvider(
            mode=settings.visible_ai_marker_mode,
            binary=settings.visible_ai_marker_binary,
            timeout_seconds=settings.visible_ai_marker_timeout_seconds,
            minimum_confidence=settings.visible_ai_marker_min_confidence,
            configured_terms_json=settings.visible_ai_marker_terms_json,
        ),
        provenance=ProvenanceRouter(
            mode=settings.c2pa_mode,
            binary=settings.c2pa_binary,
            expected_version=settings.c2pa_expected_version,
            expected_binary_sha256=settings.c2pa_expected_binary_sha256,
            timeout_seconds=settings.c2pa_timeout_seconds,
            trust_policy_id=settings.c2pa_trust_policy_id,
        ),
        proof_anchor=None,
        blockchain=None,
        signer=signer,
        transparency=transparency,
        stage_ledger=StageLedger(
            lease_seconds=settings.stage_lease_seconds,
            max_attempts=settings.stage_max_attempts,
        ),
        policies=PolicyStore(),
    )
    # The durable transparency anchor needs the container's session factory, so the
    # proof provider is resolved after the database is available.
    container.proof_anchor = build_proof_anchor(
        settings,
        transparency_log=transparency,
        session_factory=container.database.session_factory,
    )
    if (
        settings.environment == "production"
        and settings.proof_anchor_mode == "eas"
        and not getattr(container.proof_anchor, "available", False)
    ):
        reason = getattr(container.proof_anchor, "unavailable_reason", None) or "EAS_UNAVAILABLE"
        raise RuntimeError(f"Production EAS configuration cannot activate: {reason}")
    container.blockchain = BlockchainAnchorService(
        session_factory=container.database.system_session,
        provider=container.proof_anchor,
        transparency=container.transparency,
        settings=settings,
        worker_id=container.worker_identity,
    )
    # Counterparties are read from the chain through the proof provider's RPC
    # client, so failover and timeout policy have one implementation.
    container.member_registry = build_member_registry(settings, container.proof_anchor)
    container.coattestations = CoAttestationService(
        settings=settings,
        blockchain=container.blockchain,
        verifier=build_counterparty_verifier(settings),
        member_registry=container.member_registry,
        signer=container.signer,
        transparency=container.transparency,
    )
    if settings.job_backend == "redis":
        container.queue = (
            RedisStreamsJobQueue(
                settings.redis_url,
                stream_name=settings.redis_stream_name,
                consumer_group=settings.redis_consumer_group,
                maxlen=settings.redis_stream_maxlen,
            )
            if settings.redis_transport == "streams"
            else RedisJobQueue(
                settings.redis_url,
                settings.redis_queue_name,
                max_attempts=settings.redis_job_max_attempts,
                lease_seconds=settings.redis_job_lease_seconds,
            )
        )
    elif settings.job_backend == "inline" and settings.environment == "test":
        container.queue = InlineJobQueue(lambda scan_id: process_scan(container, scan_id))
    else:
        # `inline` is treated as the non-blocking local backend outside tests so an
        # older .env cannot reintroduce the v0.9 request-thread scan stall.
        container.queue = LocalThreadJobQueue(
            lambda scan_id: process_scan(container, scan_id),
            max_workers=settings.local_job_workers,
        )
    container.outbox = OutboxDispatcher(
        session_factory=container.database.system_session,
        queue=container.queue,
        max_attempts=settings.outbox_max_attempts,
    )
    return container


def initialize_database(container: Container) -> None:
    """Prepare the schema and seed the records the platform depends on.

    PostgreSQL deployments are migration-managed: ``scripts/migrate.py`` (Alembic)
    owns the schema, and this function only ensures the seed rows exist. SQLite
    quick-start keeps ``create_all`` so a fresh clone runs with no extra steps.
    """
    settings = container.settings
    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(container.database.engine)
    container.database.assert_runtime_role_safety(require_rls=settings.enable_postgres_rls)
    # API and worker containers can reach this path together after the migration
    # job exits. Serialize their check-then-insert seed workflow across processes.
    with container.database.startup_lock():
        # Tenant/bootstrap discovery is explicitly trusted cross-tenant work.
        # bind_tenant_context below removes the bypass before any policy query.
        db = container.database.system_session()
        try:
            tenant = db.get(Tenant, settings.dev_tenant_id)
            if tenant is None:
                db.add(
                    Tenant(
                        id=settings.dev_tenant_id,
                        slug=settings.dev_tenant_slug,
                        name="CreatorProof Development Tenant",
                    )
                )
                db.commit()
            register_signing_key(db, container.signer)
            # Policy versions are tenant-owned and FORCE RLS is enabled in
            # PostgreSQL. The session-level binding survives PolicyStore commits.
            bind_tenant_context(db, settings.dev_tenant_id)
            ensure_default_policy(
                db,
                tenant_id=settings.dev_tenant_id,
                signer=container.signer,
                transparency=container.transparency,
                blockchain=container.blockchain,
            )
        finally:
            db.close()
