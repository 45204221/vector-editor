"""Deterministic CPU/build-size evidence for M21.6 stroke decisions."""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path: sys.path.insert(0, SRC)

from core import native_geometry
from core.stroke_tessellation import dash_polyline as python_dash


def timed(function, paths, repeats=5):
    samples = []
    output_vertices = 0
    for _ in range(repeats):
        started = time.perf_counter()
        for points in paths:
            output_vertices += len(function(points, (8.0, 4.0)))
        samples.append((time.perf_counter() - started) * 1000.0)
    return min(samples), output_vertices // repeats


def main():
    report = {}
    for count in (100, 1000):
        paths = [((0.0, float(index)), (80.0, float(index)),
                  (80.0, float(index) + 40.0)) for index in range(count)]
        python_ms, vertices = timed(python_dash, paths)
        native_ms, native_vertices = timed(native_geometry.dash_polyline, paths)
        report[str(count)] = {"python_ms": python_ms, "native_ms": native_ms,
                              "speedup": python_ms / max(native_ms, 1e-9),
                              "line_vertices": vertices,
                              "upload_bytes_xy_float32": vertices * 8,
                              "native_vertices": native_vertices}
    # Existing triangle-list stroke vertices contain per-triangle coverage values;
    # indexing them would require a new vertex/index ABI and does not help dash
    # endpoint pairs, which are already minimal for GL_LINES.
    report["decision"] = {
        "dash": "enable C++ continuous arc-length segmentation",
        "indexed_stroke": "defer: no measured >=25% end-to-end upload win under current coverage ABI",
        "multidraw": "defer: PyQt function-table portability and command buckets need driver matrix evidence"
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__": main()
