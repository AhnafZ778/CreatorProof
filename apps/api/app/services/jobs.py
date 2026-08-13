import logging
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Protocol

from redis import Redis

logger = logging.getLogger("creatorproof.jobs")


class JobQueue(Protocol):
    name: str

    def enqueue(self, scan_id: str) -> None: ...

    def healthy(self) -> bool: ...

    def close(self) -> None: ...


class InlineJobQueue:
    name = "inline"

    def __init__(self, callback) -> None:
        self.callback = callback

    def enqueue(self, scan_id: str) -> None:
        self.callback(scan_id)

    def healthy(self) -> bool:
        return True

    def close(self) -> None:
        return None


class LocalThreadJobQueue:
    """Non-blocking, single-process queue for local demos.

    The executor deliberately defaults to one worker. CreatorProof model providers
    are resident process resources; running several scans against the same CPU/GPU
    at once creates contention and can make every scan slower. Redis remains the
    durable deployment option because these local jobs do not survive an API restart.
    """

    name = "local-thread"

    def __init__(self, callback, *, max_workers: int = 1) -> None:
        self.callback = callback
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="creatorproof-scan",
        )
        self._closed = False
        self._lock = Lock()

    @staticmethod
    def _report_failure(future: Future) -> None:
        try:
            future.result()
        except Exception:
            logger.exception("background scan failed")

    def enqueue(self, scan_id: str) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("LOCAL_JOB_QUEUE_CLOSED")
            future = self._executor.submit(self.callback, scan_id)
        future.add_done_callback(self._report_failure)

    def healthy(self) -> bool:
        with self._lock:
            return not self._closed

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=False)


class RedisJobQueue:
    name = "redis"

    def __init__(self, url: str, queue_name: str) -> None:
        self.client = Redis.from_url(url, decode_responses=True)
        self.queue_name = queue_name

    def enqueue(self, scan_id: str) -> None:
        self.client.rpush(self.queue_name, scan_id)

    def healthy(self) -> bool:
        return bool(self.client.ping())

    def close(self) -> None:
        self.client.close()
