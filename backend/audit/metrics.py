"""Bounded, PHI-free prototype latency measurements."""
from collections import deque
from threading import Lock

from backend.domain.contracts import MetricSummary, MetricsResponse, StageTimings


def summary(values: list[float]) -> MetricSummary:
    ordered = sorted(values)
    if not ordered:
        return MetricSummary(samples=0, p50Ms=0, p95Ms=0, p99Ms=0)

    def percentile(p: float) -> float:
        index = (len(ordered) - 1) * p
        lo = int(index)
        hi = min(lo + 1, len(ordered) - 1)
        return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo), 3)

    return MetricSummary(samples=len(ordered), p50Ms=percentile(.5), p95Ms=percentile(.95), p99Ms=percentile(.99))


class Metrics:
    def __init__(self):
        self._lock = Lock()
        self._requests = deque(maxlen=10000)
        self._renders = deque(maxlen=10000)
        self._render_ids: set[tuple[str, str]] = set()

    def record(self, timings: StageTimings, codes: list[str], manual: bool):
        with self._lock:
            self._requests.append((timings.model_dump(), "PROVIDER_429" in codes,
                                   "DEADLINE_EXCEEDED" in codes or "PROVIDER_TIMEOUT" in codes, manual))

    def render(self, actor_id: str, response_id: str, duration_ms: float):
        with self._lock:
            key = (actor_id, response_id)
            if key not in self._render_ids:
                self._render_ids.add(key)
                self._renders.append(duration_ms)

    def snapshot(self) -> MetricsResponse:
        with self._lock:
            rows = list(self._requests)
            count = len(rows)
            names = list(StageTimings.model_fields)
            return MetricsResponse(
                requestCount=count,
                stages={name: summary([row[0][name] for row in rows]) for name in names},
                provider429Rate=sum(row[1] for row in rows) / count if count else 0,
                deadlineExceededRate=sum(row[2] for row in rows) / count if count else 0,
                degradedModeRate=sum(row[3] for row in rows) / count if count else 0,
                timeToSafeRender=summary(list(self._renders)), targetP95Ms=4000, targetIsGuarantee=False,
            )

