import logging

from redis import Redis

from app.container import build_container, initialize_database
from app.core.config import Settings
from app.services.evidence import process_scan

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("creatorproof.worker")


def main() -> None:
    settings = Settings()
    if settings.job_backend != "redis":
        raise RuntimeError("Worker requires CREATORPROOF_JOB_BACKEND=redis")
    container = build_container(settings)
    initialize_database(container)
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    logger.info("worker_ready queue=%s", settings.redis_queue_name)
    while True:
        result = client.brpop(settings.redis_queue_name, timeout=5)
        if result is None:
            continue
        _, scan_id = result
        try:
            process_scan(container, scan_id)
        except Exception:
            logger.exception("scan_failed scan_id=%s", scan_id)


if __name__ == "__main__":
    main()
