"""矢量编辑器无窗口性能基准。

默认只运行 100/1000 图元安全档。超过 1000 必须显式传入 --allow-large，
避免在开发机上意外执行高内存、长耗时测试。
"""

import argparse
import json
import os
import sys
import time
import tracemalloc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtGui import QImage, QPainter, QTransform

from core.canvas import Canvas
from core.geometry import GeometryCache
from core.gpu_arena import GpuArena
from core.gpu_buffers import GpuBufferBuilder, plan_gpu_upload
from core.pipeline_debug import build_pipeline_snapshot
from core.rendering import CommandQPainterBackend, QPainterBackend


def elapsed_ms(action):
    start = time.perf_counter()
    result = action()
    return (time.perf_counter() - start) * 1000.0, result


def build_canvas(count):
    canvas = Canvas(2000, 1500)
    canvas.snap_to_grid = False
    columns, spacing, size = 200, 9, 6
    for index in range(count):
        x = 20 + (index % columns) * spacing
        y = 20 + (index // columns) * spacing
        shape = canvas.create_rectangle(x, y, size, size)
        shape.z_index = index
        canvas.shapes.append(shape)
    return canvas


def render_canvas(canvas, viewport=None):
    image = QImage(int(canvas.width), int(canvas.height), QImage.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    backend = QPainterBackend()
    backend.sync_document(canvas, canvas.consume_render_dirty_flags())
    backend.render(painter, viewport)
    painter.end()
    return image


def run_case(count):
    tracemalloc.start()
    build_ms, canvas = elapsed_ms(lambda: build_canvas(count))
    update_ms, _ = elapsed_ms(lambda: canvas.update_world_state(emit=False))
    geometry_cache = GeometryCache()
    geometry_build_ms, _ = elapsed_ms(lambda: geometry_cache.sync_snapshot(canvas.create_render_snapshot()))
    gpu_builder = GpuBufferBuilder()
    gpu_previous_frame = gpu_builder.build(geometry_cache)
    gpu_arena = GpuArena()
    arena_build_ms, _ = elapsed_ms(lambda: gpu_arena.rebuild(geometry_cache))
    gpu_arena.mark_uploaded()
    canvas.consume_render_delta(force_full=True)
    canvas.begin_history_transaction("benchmark")
    incremental_ms, _ = elapsed_ms(lambda: canvas.move_shapes([canvas.shapes[0]], 1, 0))
    delta_ms, delta = elapsed_ms(canvas.consume_render_delta)
    geometry_delta_ms, _ = elapsed_ms(lambda: geometry_cache.apply_delta(delta))
    arena_update_ms, _ = elapsed_ms(lambda: gpu_arena.apply_delta(delta, geometry_cache))
    arena_plan_ms, arena_plan = elapsed_ms(gpu_arena.build_upload_plan)
    gpu_buffer_ms, gpu_frame = elapsed_ms(lambda: gpu_builder.build(geometry_cache))
    gpu_plan_ms, gpu_plan = elapsed_ms(lambda: plan_gpu_upload(gpu_previous_frame, gpu_frame))
    gpu_culled_ms, gpu_culled_frame = elapsed_ms(
        lambda: gpu_builder.build(geometry_cache, (0, 0, 320, 240)))
    debug_backend = CommandQPainterBackend(canvas)
    debug_backend.cache = geometry_cache
    pipeline_debug_ms, pipeline_debug = elapsed_ms(
        lambda: build_pipeline_snapshot(
            canvas, debug_backend, QTransform(), (2000, 1500),
            (0, 0, 2000, 1500), canvas.shapes[0].id))
    snapshot_ms, snapshot = elapsed_ms(canvas.create_render_snapshot)
    snapshot_bytes = len(json.dumps(snapshot.shapes, ensure_ascii=False, default=str).encode("utf-8"))
    render_ms, image = elapsed_ms(lambda: render_canvas(canvas))
    from PyQt5.QtCore import QRectF
    culled_ms, culled_image = elapsed_ms(lambda: render_canvas(canvas, QRectF(0, 0, 320, 240)))
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del image, culled_image, snapshot, canvas
    return {
        "shapes": count,
        "build_ms": round(build_ms, 2),
        "world_update_ms": round(update_ms, 2),
        "incremental_move_ms": round(incremental_ms, 2),
        "render_delta_ms": round(delta_ms, 2),
        "render_delta_shapes": len(delta.upserted_shapes),
        "geometry_build_ms": round(geometry_build_ms, 2),
        "geometry_delta_ms": round(geometry_delta_ms, 2),
        "render_primitives": len(geometry_cache.primitives()),
        "gpu_buffer_ms": round(gpu_buffer_ms, 2),
        "gpu_vertices": gpu_frame.vertex_count,
        "gpu_batches": len(gpu_frame.batches),
        "gpu_upload_plan_ms": round(gpu_plan_ms, 2),
        "gpu_upload_kind": gpu_plan.kind.value,
        "gpu_upload_bytes": gpu_plan.byte_count,
        "gpu_upload_ranges": len(gpu_plan.ranges),
        "arena_build_ms": round(arena_build_ms, 2),
        "arena_update_ms": round(arena_update_ms, 2),
        "arena_shapes_touched": gpu_arena.last_shapes_touched,
        "arena_primitives_expanded": gpu_arena.last_primitives_expanded,
        "arena_upload_plan_ms": round(arena_plan_ms, 2),
        "arena_upload_kind": arena_plan.kind.value,
        "arena_upload_bytes": arena_plan.byte_count,
        "arena_upload_ranges": len(arena_plan.ranges),
        "arena_allocations": gpu_arena.allocation_count,
        "arena_fragmentation": round(gpu_arena.fragmentation_ratio, 4),
        "gpu_culled_buffer_ms": round(gpu_culled_ms, 2),
        "gpu_culled_primitives": gpu_culled_frame.source_primitive_count,
        "pipeline_debug_ms": round(pipeline_debug_ms, 2),
        "pipeline_debug_triangles": len(pipeline_debug.primitive_triangles),
        "snapshot_ms": round(snapshot_ms, 2),
        "snapshot_mb": round(snapshot_bytes / 1024 / 1024, 2),
        "render_ms": round(render_ms, 2),
        "culled_render_ms": round(culled_ms, 2),
        "estimated_fps": round(1000.0 / render_ms, 1) if render_ms else None,
        "python_peak_mb": round(peak / 1024 / 1024, 2),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--counts", nargs="+", type=int, default=[100, 1000])
    parser.add_argument("--allow-large", action="store_true")
    args = parser.parse_args()
    if any(count <= 0 for count in args.counts):
        parser.error("图元数量必须大于 0")
    if any(count > 1000 for count in args.counts) and not args.allow_large:
        parser.error("超过 1000 图元需要显式添加 --allow-large")
    print(json.dumps([run_case(count) for count in args.counts], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
