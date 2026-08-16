"""Low-overhead runtime performance samples, independent from document state."""

from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import platform
import sys
from time import perf_counter_ns

from PyQt5.QtCore import QT_VERSION_STR


class PerformanceProfiler:
    """Collect bounded timing samples and gauges for UI and JSON reports."""

    def __init__(self, capacity=120):
        self.capacity = max(1, int(capacity))
        self.enabled = True
        self._samples = defaultdict(lambda: deque(maxlen=self.capacity))
        self._gauges = {}
        self._metadata = {
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "qt": QT_VERSION_STR,
            "platform": platform.platform(),
            "executable": sys.executable,
        }

    def record_ms(self, name, value):
        if self.enabled:
            self._samples[str(name)].append(float(value))

    @contextmanager
    def measure(self, name):
        if not self.enabled:
            yield
            return
        start = perf_counter_ns()
        try:
            yield
        finally:
            self.record_ms(name, (perf_counter_ns() - start) / 1_000_000.0)

    def set_gauge(self, name, value):
        if isinstance(value, (int, float, str, bool)) or value is None:
            self._gauges[str(name)] = value

    def set_metadata(self, name, value):
        if isinstance(value, (int, float, str, bool)) or value is None:
            self._metadata[str(name)] = value

    def samples(self, name):
        return tuple(self._samples.get(name, ()))

    def clear(self):
        self._samples.clear()
        self._gauges.clear()

    @staticmethod
    def _summary(values):
        if not values:
            return {"count": 0, "latest": None, "average": None,
                    "p95": None, "maximum": None}
        ordered = sorted(values)
        p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
        return {
            "count": len(values),
            "latest": values[-1],
            "average": sum(values) / len(values),
            "p95": ordered[p95_index],
            "maximum": ordered[-1],
        }

    def snapshot(self):
        samples = {name: list(values) for name, values in sorted(self._samples.items())}
        return {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "enabled": self.enabled,
            "capacity": self.capacity,
            "metadata": dict(sorted(self._metadata.items())),
            "gauges": dict(sorted(self._gauges.items())),
            "summaries": {name: self._summary(values)
                          for name, values in samples.items()},
            "samples_ms": samples,
        }

    def export_json(self, file_path):
        with open(file_path, "w", encoding="utf-8") as report:
            json.dump(self.snapshot(), report, ensure_ascii=False, indent=2)

