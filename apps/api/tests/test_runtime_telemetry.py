from app.services.runtime_telemetry import (
    current_telemetry,
    increment_counter,
    record_duration,
    record_observation,
    telemetry_scope,
)


def test_runtime_telemetry_aggregates_without_exposing_raw_events():
    assert current_telemetry() is None
    with telemetry_scope({"bundle_id": "bundle-test"}) as telemetry:
        increment_counter("cache_hit")
        increment_counter("cache_hit")
        record_duration("retrieval", 10.0)
        record_duration("retrieval", 20.0)
        record_observation("copy_score", 0.2)
        record_observation("copy_score", 0.8)
        snapshot = telemetry.snapshot()

    assert current_telemetry() is None
    assert snapshot["counters"]["cache_hit"] == 2
    assert snapshot["timings_ms"]["retrieval"]["mean"] == 15.0
    assert snapshot["score_summaries"]["copy_score"] == {
        "count": 2,
        "mean": 0.5,
        "minimum": 0.2,
        "maximum": 0.8,
    }


def test_runtime_telemetry_context_is_reset_after_exception():
    try:
        with telemetry_scope():
            raise RuntimeError("expected")
    except RuntimeError:
        pass

    assert current_telemetry() is None
