from dataclasses import dataclass

from app.core.config import Settings
from app.db import Base, Database, build_database
from app.models import Tenant
from app.providers.ai_retrieval import SSCDVisualEmbeddingProvider
from app.providers.aligned_perceptual import AlignedPerceptualVerifier
from app.providers.fingerprints import BaselineFingerprintProvider
from app.providers.geometry import ORBGeometricVerifier
from app.providers.proof import build_proof_anchor
from app.providers.provenance import ProvenanceRouter
from app.providers.style_retrieval import StyleEmbeddingRouter
from app.providers.synthetic_detection import SyntheticDetectorRouter
from app.providers.visible_markers import VisibleAIMarkerProvider
from app.services.evidence import process_scan
from app.services.jobs import InlineJobQueue, JobQueue, LocalThreadJobQueue, RedisJobQueue
from app.services.storage import LocalObjectStore


@dataclass(slots=True)
class Container:
    settings: Settings
    database: Database
    storage: LocalObjectStore
    fingerprints: BaselineFingerprintProvider
    ai_retrieval: SSCDVisualEmbeddingProvider
    style_retrieval: StyleEmbeddingRouter
    geometry: ORBGeometricVerifier
    aligned_perceptual: AlignedPerceptualVerifier
    synthetic_detection: SyntheticDetectorRouter
    visible_markers: VisibleAIMarkerProvider
    provenance: ProvenanceRouter
    proof_anchor: object
    queue: JobQueue | None = None


def build_container(settings: Settings) -> Container:
    container = Container(
        settings=settings,
        database=build_database(settings),
        storage=LocalObjectStore(settings.storage_root),
        fingerprints=BaselineFingerprintProvider(),
        ai_retrieval=SSCDVisualEmbeddingProvider(
            settings.sscd_model_path,
            settings.sscd_device,
        ),
        style_retrieval=StyleEmbeddingRouter(
            mode=settings.style_provider,
            csd_repo_path=settings.style_csd_repo_path,
            csd_model_path=settings.style_csd_model_path,
            device=settings.style_device,
            allow_legacy_pickle=settings.style_allow_legacy_pickle,
            expected_sha256=settings.style_csd_expected_sha256,
        ),
        geometry=ORBGeometricVerifier(),
        aligned_perceptual=AlignedPerceptualVerifier(),
        synthetic_detection=SyntheticDetectorRouter(
            mode=settings.synthetic_detector,
            community_model_path=settings.synthetic_community_model_path,
            torchscript_model_path=settings.synthetic_torchscript_model_path,
            device=settings.synthetic_device,
            external_detectors_json=settings.synthetic_external_detectors_json,
            calibration_path=settings.synthetic_calibration_path,
            min_calibration_samples=settings.synthetic_min_calibration_samples,
            min_calibration_class_samples=settings.synthetic_min_calibration_class_samples,
            external_timeout_seconds=settings.synthetic_external_timeout_seconds,
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
            timeout_seconds=settings.c2pa_timeout_seconds,
        ),
        proof_anchor=build_proof_anchor(settings),
    )
    if settings.job_backend == "redis":
        container.queue = RedisJobQueue(settings.redis_url, settings.redis_queue_name)
    elif settings.job_backend == "inline" and settings.environment == "test":
        container.queue = InlineJobQueue(lambda scan_id: process_scan(container, scan_id))
    else:
        # `inline` is treated as the non-blocking local backend outside tests so an
        # older .env cannot reintroduce the v0.9 request-thread scan stall.
        container.queue = LocalThreadJobQueue(
            lambda scan_id: process_scan(container, scan_id),
            max_workers=settings.local_job_workers,
        )
    return container


def initialize_database(container: Container) -> None:
    Base.metadata.create_all(container.database.engine)
    db = container.database.session_factory()
    try:
        tenant = db.get(Tenant, container.settings.dev_tenant_id)
        if tenant is None:
            db.add(
                Tenant(
                    id=container.settings.dev_tenant_id,
                    slug=container.settings.dev_tenant_slug,
                    name="CreatorProof Development Tenant",
                )
            )
            db.commit()
    finally:
        db.close()
