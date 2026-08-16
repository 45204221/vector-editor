"""Safe 100/1000-path comparison for Python and optional C++ tessellation."""

import argparse
import json
import os
import statistics
import sys
import time


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from core import native_geometry


RECTANGLE = ((0.0, 0.0), (60.0, 0.0), (60.0, 40.0), (0.0, 40.0))


def measure(count, enabled, repeats=3):
    native_geometry.set_native_enabled(enabled)
    samples = []
    vertex_count = 0
    for _ in range(repeats):
        start = time.perf_counter()
        total = 0
        for _ in range(count):
            total += len(native_geometry.tessellate_stroke_coverage(
                RECTANGLE, 3.0, closed=True, join="miter", cap="butt"))
        samples.append((time.perf_counter() - start) * 1000.0)
        vertex_count = total
    return statistics.median(samples), vertex_count


def run_case(count):
    python_ms, python_vertices = measure(count, False)
    if native_geometry.is_available():
        native_ms, native_vertices = measure(count, True)
        speedup = python_ms / native_ms if native_ms else None
    else:
        native_ms = speedup = None
        native_vertices = 0
    return {
        "paths": count,
        "vertices": python_vertices,
        "native_vertices": native_vertices,
        "python_ms": round(python_ms, 3),
        "native_ms": round(native_ms, 3) if native_ms is not None else None,
        "speedup": round(speedup, 2) if speedup is not None else None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--counts", nargs="+", type=int, default=[100, 1000])
    parser.add_argument("--allow-large", action="store_true")
    args = parser.parse_args()
    if any(count <= 0 for count in args.counts):
        parser.error("路径数量必须大于 0")
    if any(count > 1000 for count in args.counts) and not args.allow_large:
        parser.error("超过 1000 条路径需要显式添加 --allow-large")
    result = {
        "backend": native_geometry.backend_info(),
        "cases": [run_case(count) for count in args.counts],
    }
    native_geometry.set_native_enabled(True)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
