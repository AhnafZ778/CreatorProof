from collections import defaultdict

from app.services.jobs import RedisJobQueue


class FakeRedis:
    def __init__(self) -> None:
        self.lists = defaultdict(list)
        self.sorted_sets = defaultdict(dict)

    def lpush(self, key, value):
        self.lists[key].insert(0, value)
        return len(self.lists[key])

    def brpoplpush(self, source, destination, timeout):
        del timeout
        if not self.lists[source]:
            return None
        value = self.lists[source].pop()
        self.lists[destination].insert(0, value)
        return value

    def zadd(self, key, mapping, xx=False):
        count = 0
        for member, score in mapping.items():
            if xx and member not in self.sorted_sets[key]:
                continue
            self.sorted_sets[key][member] = float(score)
            count += 1
        return count

    def zrangebyscore(self, key, minimum, maximum, start=0, num=100):
        del minimum
        selected = [
            member
            for member, score in sorted(
                self.sorted_sets[key].items(), key=lambda item: (item[1], item[0])
            )
            if score <= float(maximum)
        ]
        return selected[start : start + num]

    def eval(self, script, key_count, *arguments):
        keys = arguments[:key_count]
        values = arguments[key_count:]
        processing, leases = keys[:2]
        raw = values[0]
        removed = 0
        if raw in self.lists[processing]:
            self.lists[processing].remove(raw)
            removed = 1
        self.sorted_sets[leases].pop(raw, None)
        if "LPUSH" in script and removed:
            destination = keys[2]
            replacement = values[1]
            self.lists[destination].insert(0, replacement)
        return removed

    def ping(self):
        return True

    def close(self):
        return None


def _queue(*, max_attempts=3, lease_seconds=60):
    client = FakeRedis()
    queue = RedisJobQueue(
        "redis://unused",
        "creatorproof:test",
        max_attempts=max_attempts,
        lease_seconds=lease_seconds,
        client=client,
    )
    return queue, client


def test_job_remains_in_processing_until_explicit_acknowledgment():
    queue, client = _queue()
    queue.enqueue("scan-001")

    job = queue.claim(timeout=1)

    assert job is not None
    assert job.scan_id == "scan-001"
    assert job.attempt == 0
    assert client.lists[queue.queue_name] == []
    assert client.lists[queue.processing_name] == [job.raw_payload]
    assert job.raw_payload in client.sorted_sets[queue.lease_name]

    assert queue.acknowledge(job) is True
    assert client.lists[queue.processing_name] == []
    assert client.sorted_sets[queue.lease_name] == {}


def test_failed_jobs_retry_then_move_to_dead_letter_queue():
    queue, client = _queue(max_attempts=2)
    queue.enqueue("scan-002")
    first = queue.claim(timeout=1)

    assert queue.fail(first, "TRANSIENT_FAILURE") == "REQUEUED"
    retry = queue.claim(timeout=1)
    assert retry.scan_id == first.scan_id
    assert retry.job_id == first.job_id
    assert retry.attempt == 1

    assert queue.fail(retry, "REPEATED_FAILURE") == "DEAD_LETTERED"
    assert client.lists[queue.processing_name] == []
    assert len(client.lists[queue.dead_name]) == 1
    dead = queue._decode(client.lists[queue.dead_name][0])
    assert dead.attempt == 2


def test_expired_lease_is_recovered_without_losing_job():
    queue, client = _queue(max_attempts=3, lease_seconds=60)
    queue.enqueue("scan-003")
    claimed = queue.claim(timeout=1)
    client.sorted_sets[queue.lease_name][claimed.raw_payload] = 10.0

    result = queue.recover_stale(now=11.0)

    assert result == {
        "expired": 1,
        "recovered": 1,
        "dead_lettered": 0,
        "malformed": 0,
    }
    assert client.lists[queue.processing_name] == []
    recovered = queue.claim(timeout=1)
    assert recovered.scan_id == claimed.scan_id
    assert recovered.attempt == 1
