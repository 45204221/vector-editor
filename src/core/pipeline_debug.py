"""Read-only snapshots and overlays for the rendering-pipeline laboratory."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QBrush, QPainter, QPen, QPolygonF

from .geometry import GeometryCache, _map_point
from .native_geometry import backend_name as geometry_backend_name
from .gpu_buffers import (VERTEX_COMPONENTS, VERTEX_STRIDE_BYTES,
                          VERTEX_STRIDE_FLOATS, encode_gpu_primitive)


Point = Tuple[float, float]
Bounds = Tuple[float, float, float, float]
MAX_OVERLAY_PRIMITIVES = 96
MAX_OVERLAY_TRIANGLES = 4000


class PipelineDebugMode(str, Enum):
    FINAL = "final"
    WIREFRAME = "wireframe"
    PRIMITIVE = "primitive"
    BATCH = "batch"
    CLIP = "clip"
    OVERDRAW = "overdraw"


@dataclass(frozen=True)
class VertexTrace:
    local: Point
    world: Point
    device: Point
    clip: Tuple[float, float, float, float]
    ndc: Point
    screen: Point
    coverage: float


@dataclass(frozen=True)
class PrimitiveTrace:
    primitive_index: int
    topology: str
    render_pass: int
    source_vertex_count: int
    gpu_vertex_count: int
    world_bounds: Bounds
    model_matrix: Tuple[float, float, float, float, float, float]
    vertices: Tuple[VertexTrace, ...]


@dataclass(frozen=True)
class DebugTriangle:
    points: Tuple[Point, Point, Point]
    group_index: int


@dataclass(frozen=True)
class PipelineSnapshot:
    backend_name: str
    revision: int
    selected_shape_id: Optional[str]
    stages: Tuple[Tuple[str, str], ...]
    state: Tuple[Tuple[str, str], ...]
    primitive_traces: Tuple[PrimitiveTrace, ...]
    primitive_triangles: Tuple[DebugTriangle, ...]
    batch_triangles: Tuple[DebugTriangle, ...]
    viewport_bounds: Bounds
    vertex_layout: str
    shader_summary: str
    overdraw_note: str


def _transform_tuple(transform) -> Tuple[float, float, float, float, float, float]:
    return (float(transform.m11()), float(transform.m12()),
            float(transform.m21()), float(transform.m22()),
            float(transform.dx()), float(transform.dy()))


def _map_device(point: Point, transform) -> Point:
    mapped = transform.map(QPointF(*point))
    return float(mapped.x()), float(mapped.y())


def _vertex_trace(local, world, coverage, view_transform, device_size):
    device = _map_device(world, view_transform)
    width, height = max(1.0, float(device_size[0])), max(1.0, float(device_size[1]))
    ndc = (device[0] * 2.0 / width - 1.0,
           1.0 - device[1] * 2.0 / height)
    return VertexTrace(tuple(map(float, local)), tuple(map(float, world)), device,
                       (ndc[0], ndc[1], 0.0, 1.0), ndc, device, float(coverage))


def _triangles_from_vertices(vertices, first_vertex=0, vertex_count=None, group_index=0,
                             max_triangles=MAX_OVERLAY_TRIANGLES):
    total = len(vertices) // VERTEX_STRIDE_FLOATS
    if vertex_count is None:
        vertex_count = total - first_vertex
    points = []
    last = min(total, first_vertex + vertex_count)
    for vertex in range(first_vertex, last):
        offset = vertex * VERTEX_STRIDE_FLOATS
        points.append((float(vertices[offset]), float(vertices[offset + 1])))
    return tuple(DebugTriangle((points[index], points[index + 1], points[index + 2]),
                               group_index)
                 for index in range(0, min(len(points) - 2, max_triangles * 3), 3))


def _cache_for(canvas, backend):
    cache = getattr(backend, "cache", None)
    if isinstance(cache, GeometryCache) and cache.revision >= 0:
        return cache, False
    cache = GeometryCache()
    cache.sync_snapshot(canvas.create_render_snapshot())
    return cache, True


def build_pipeline_snapshot(canvas, backend, view_transform, device_size,
                            viewport_bounds: Bounds,
                            selected_shape_id: Optional[str] = None,
                            debug_mode: str = PipelineDebugMode.PRIMITIVE.value) -> PipelineSnapshot:
    """Capture the current render pipeline without consuming or mutating RenderDelta."""
    cache, transient_cache = _cache_for(canvas, backend)
    view_matrix = _transform_tuple(view_transform)
    primitives = cache.primitives(viewport_bounds)
    selected = tuple(cache.primitives_for_shape(selected_shape_id)) if selected_shape_id else ()
    try:
        mode = PipelineDebugMode(debug_mode)
    except ValueError:
        mode = PipelineDebugMode.FINAL
    if mode != PipelineDebugMode.FINAL:
        # GeometryCache is pass-major, so a plain prefix would show only fills in
        # large scenes. Sample both fill and stroke passes while remaining bounded.
        per_pass = max(1, MAX_OVERLAY_PRIMITIVES // 2)
        overlay_primitives = tuple(
            primitive
            for render_pass in (1, 2)
            for primitive in tuple(item for item in primitives
                                   if item.render_pass == render_pass)[:per_pass])
    else:
        overlay_primitives = ()

    primitive_triangles = []
    primitive_traces = []
    encoded_by_identity = {}
    for trace_index, primitive in enumerate(selected):
        topology, _, encoded = encode_gpu_primitive(primitive)
        encoded_by_identity[id(primitive)] = (topology, encoded)
        gpu_vertices = len(encoded) // VERTEX_STRIDE_FLOATS
        traces = []
        # Source vertices expose the model/world/view transform chain. Coverage comes
        # from the expanded stream and is therefore reported separately in state.
        for local in primitive.vertices[:12]:
            world = _map_point(local, primitive.transform)
            traces.append(_vertex_trace(local, world, 1.0, view_transform, device_size))
        primitive_traces.append(PrimitiveTrace(
            trace_index, primitive.topology.value, primitive.render_pass,
            len(primitive.vertices), gpu_vertices, primitive.world_bounds,
            primitive.transform, tuple(traces)))

    sampled_gpu_vertices = 0
    sampled_batch_count = 0
    last_batch_key = None
    reference_batch_triangles = []
    for global_index, primitive in enumerate(overlay_primitives):
        topology, encoded = encoded_by_identity.get(id(primitive), (None, None))
        if encoded is None:
            topology, _, encoded = encode_gpu_primitive(primitive)
        if not encoded or getattr(topology, "value", topology) != "triangles":
            continue
        sampled_gpu_vertices += len(encoded) // VERTEX_STRIDE_FLOATS
        triangles = _triangles_from_vertices(
            encoded, group_index=global_index,
            max_triangles=max(0, MAX_OVERLAY_TRIANGLES - len(primitive_triangles)))
        primitive_triangles.extend(triangles)
        batch_key = (primitive.render_pass, getattr(topology, "value", topology))
        if batch_key != last_batch_key:
            sampled_batch_count += 1
            last_batch_key = batch_key
        reference_batch_triangles.extend(
            DebugTriangle(item.points, sampled_batch_count - 1) for item in triangles)
        if len(primitive_triangles) >= MAX_OVERLAY_TRIANGLES:
            break

    # Build the same flattened command stream used by the command backend. For the
    # OpenGL backend prefer its live Arena page so batch overlays match VBO slots.
    arena = getattr(backend, "arena", None)
    if arena is not None and getattr(arena, "allocations", None):
        frame = arena.build_frame(cache, viewport_bounds)
        vertex_data = arena.page.vertices
        batch_triangles_list = []
        if mode == PipelineDebugMode.BATCH:
            for batch_index, batch in enumerate(frame.batches):
                remaining = MAX_OVERLAY_TRIANGLES - len(batch_triangles_list)
                if remaining <= 0:
                    break
                batch_triangles_list.extend(_triangles_from_vertices(
                    vertex_data, batch.first_vertex, batch.vertex_count, batch_index,
                    remaining))
        batch_triangles = tuple(batch_triangles_list)
        gpu_vertices = frame.visible_vertex_count
        batch_count = len(frame.batches)
        allocation_count = arena.allocation_count
        source_primitive_count = frame.source_primitive_count
        source_label = "live GpuArena/VBO layout"
    else:
        batch_triangles = tuple(reference_batch_triangles)
        gpu_vertices = sampled_gpu_vertices
        batch_count = sampled_batch_count
        allocation_count = 0
        source_primitive_count = len(primitives)
        source_label = (f"reference GPU encoder · sampled {len(overlay_primitives)}/"
                        f"{len(primitives)} primitives")

    backend_name = type(backend).__name__
    shape_count = len(canvas.shapes)
    experiment_getter = getattr(backend, "experiment_state", None)
    experiment = experiment_getter() if experiment_getter else {
        "shader_mode": "QPainter fixed",
        "blend_mode": "QPainter composition",
        "clip_mode": "inactive",
        "effective_clip_mode": "inactive",
        "stencil_bits": 0,
        "time_uniform": 0.0,
        "warning": "",
    }
    offscreen_getter = getattr(backend, "offscreen_state", None)
    offscreen = offscreen_getter() if offscreen_getter else {
        "picking_mode": "cpu", "target_valid": False, "target_size": (0, 0),
        "attachment": "inactive", "mapped_shapes": 0, "matched": True,
        "cpu_ms": 0.0, "gpu_ms": 0.0, "warning": "",
        "color_target_size": (0, 0), "color_target_valid": False,
        "post_target_valid": False, "postprocess_effect": "none",
        "offscreen_ms": 0.0, "offscreen_bytes": 0, "offscreen_error": "",
    }
    instancing_getter = getattr(backend, "instancing_state", None)
    instancing = instancing_getter() if instancing_getter else {
        "enabled": False, "count": 0, "resources_valid": False,
        "draw_calls": 0, "instance_bytes": 0, "upload_count": 0,
        "sprite_mode": "inactive", "error": "",
    }
    text_getter = getattr(backend, "gpu_text_state", None)
    gpu_text = text_getter() if text_getter else {
        "enabled": False, "resources_valid": False, "unique_glyphs": 0,
        "rendered_glyphs": 0, "vertices": 0, "vbo_bytes": 0,
        "draw_calls": 0, "upload_count": 0, "fallback_commands": 0,
        "error": "",
    }
    stages = (
        ("1  Document", f"{shape_count} shapes · revision {cache.revision}"),
        ("2  Geometry", f"{source_primitive_count} visible RenderPrimitive"),
        ("3  Tessellation", f"{len(primitive_triangles)} overlay triangles (bounded)"),
        ("4  Vertex Stream", f"{gpu_vertices} vertices · {VERTEX_STRIDE_BYTES} B stride"),
        ("5  View / Clip", f"viewport {tuple(round(value, 1) for value in viewport_bounds)}"),
        ("6  Raster / Fragment",
         f"GL_TRIANGLES · {experiment['shader_mode']} · clip {experiment['effective_clip_mode']}"),
        ("7  Blend / Output", experiment["blend_mode"]),
        ("8  Offscreen / Pick",
         f"{offscreen['picking_mode']} · ID-FBO "
         f"{'ready' if offscreen['target_valid'] else 'off'} {offscreen['target_size']}"),
        ("9  Texture / Instancing / Text",
         f"{instancing['count'] if instancing['enabled'] else 0} sprites · "
         f"{instancing['draw_calls']} draw · "
         f"{gpu_text['rendered_glyphs'] if gpu_text['enabled'] else 0} glyphs · "
         f"{gpu_text['draw_calls']} text draw"),
    )
    state = (
        ("后端", backend_name),
        ("几何内核", geometry_backend_name()),
        ("缓存来源", "temporary GeometryCompiler" if transient_cache else "backend GeometryCache"),
        ("GPU 数据来源", source_label),
        ("选中图元", selected_shape_id or "—"),
        ("选中 Primitive", str(len(selected))),
        ("可见 Primitive", str(source_primitive_count)),
        ("GPU 顶点", str(gpu_vertices)),
        ("绘制批次", str(batch_count)),
        ("Arena allocations", str(allocation_count)),
        ("顶点属性", ", ".join(VERTEX_COMPONENTS)),
        ("u_transform", str(tuple(round(value, 4) for value in view_matrix[:4]))),
        ("u_translate", str(tuple(round(value, 2) for value in view_matrix[4:]))),
        ("u_viewport", str(tuple(int(value) for value in device_size))),
        ("u_shader_mode", experiment["shader_mode"]),
        ("u_time", f"{experiment['time_uniform']:.3f}"),
        ("Blend", experiment["blend_mode"]),
        ("Clip 请求/实际",
         f"{experiment['clip_mode']} / {experiment['effective_clip_mode']}"),
        ("Stencil bits", str(experiment["stencil_bits"])),
        ("实验提示", experiment["warning"] or "—"),
        ("Picking 模式", offscreen["picking_mode"]),
        ("ID RenderTarget", f"{offscreen['target_size']} · {offscreen['attachment']}"),
        ("ID 映射", str(offscreen["mapped_shapes"])),
        ("拾取 CPU/GPU ms",
         f"{offscreen['cpu_ms']:.4f} / {offscreen['gpu_ms']:.4f}"),
        ("拾取一致", str(offscreen["matched"])),
        ("离屏提示", offscreen["warning"] or "—"),
        ("Color/Post FBO", f"{offscreen['color_target_size']} · "
         f"{offscreen['color_target_valid']}/{offscreen['post_target_valid']}"),
        ("Postprocess", offscreen["postprocess_effect"]),
        ("离屏 readback", f"{offscreen['offscreen_ms']:.3f} ms · "
         f"{offscreen['offscreen_bytes'] / (1024 * 1024):.1f} MiB"),
        ("离屏错误", offscreen["offscreen_error"] or "—"),
        ("Instancing", f"enabled={instancing['enabled']} · count={instancing['count']}"),
        ("Instance buffer", f"{instancing['instance_bytes']} bytes · "
         f"uploads {instancing['upload_count']}"),
        ("Instanced draw", f"{instancing['draw_calls']} · "
         f"resources={instancing['resources_valid']}"),
        ("Instancing 错误", instancing["error"] or "—"),
        ("GPU Text", f"enabled={gpu_text['enabled']} · "
         f"glyphs {gpu_text['unique_glyphs']}/{gpu_text['rendered_glyphs']}"),
        ("Glyph VBO", f"{gpu_text['vertices']} vertices · "
         f"{gpu_text['vbo_bytes']} bytes · uploads {gpu_text['upload_count']}"),
        ("GPU Text draw", f"{gpu_text['draw_calls']} · "
         f"fallback {gpu_text['fallback_commands']} · "
         f"resources={gpu_text['resources_valid']}"),
        ("GPU Text 错误", gpu_text["error"] or "—"),
    )
    return PipelineSnapshot(
        backend_name, cache.revision, selected_shape_id, stages, state,
        tuple(sorted(primitive_traces, key=lambda item: item.primitive_index)),
        tuple(primitive_triangles), batch_triangles, viewport_bounds,
        f"float32 interleaved ({', '.join(VERTEX_COMPONENTS)}) · {VERTEX_STRIDE_BYTES} bytes",
        ("Vertex: scene position → device → clip; Fragment: "
         f"{experiment['shader_mode']} → {experiment['blend_mode']} blend; "
         f"clip={experiment['effective_clip_mode']}"),
        "Overdraw 为基于真实三角形的透明叠加近似，不是硬件 fragment 精确计数。",
    )


_DEBUG_COLORS = (
    "#00B7FF", "#FFB000", "#8CE26B", "#D979FF", "#FF5F6D",
    "#36D1A5", "#FFE45E", "#739BFF", "#F78FB3", "#9AECDB",
)


def draw_pipeline_overlay(painter: QPainter, snapshot: PipelineSnapshot,
                          mode: str) -> None:
    """Draw a read-only QPainter overlay over any production backend."""
    try:
        mode = PipelineDebugMode(mode)
    except ValueError:
        mode = PipelineDebugMode.FINAL
    if mode == PipelineDebugMode.FINAL:
        return
    triangles = (snapshot.batch_triangles if mode == PipelineDebugMode.BATCH
                 else snapshot.primitive_triangles)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, False)
    if mode == PipelineDebugMode.CLIP:
        left, top, right, bottom = snapshot.viewport_bounds
        pen = QPen(QColor("#FF2D55")); pen.setWidthF(2.0); pen.setCosmetic(True)
        painter.setPen(pen); painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(left, top, right - left, bottom - top))
    elif mode == PipelineDebugMode.WIREFRAME:
        pen = QPen(QColor("#00C8FF")); pen.setWidthF(1.0); pen.setCosmetic(True)
        painter.setPen(pen); painter.setBrush(Qt.NoBrush)
        for triangle in triangles:
            painter.drawPolygon(QPolygonF([QPointF(*point) for point in triangle.points]))
    elif mode == PipelineDebugMode.OVERDRAW:
        painter.setCompositionMode(QPainter.CompositionMode_Plus)
        painter.setPen(Qt.NoPen); painter.setBrush(QBrush(QColor(255, 34, 34, 22)))
        for triangle in triangles:
            painter.drawPolygon(QPolygonF([QPointF(*point) for point in triangle.points]))
    else:
        painter.setPen(Qt.NoPen)
        for triangle in triangles:
            color = QColor(_DEBUG_COLORS[triangle.group_index % len(_DEBUG_COLORS)])
            color.setAlpha(105)
            painter.setBrush(QBrush(color))
            painter.drawPolygon(QPolygonF([QPointF(*point) for point in triangle.points]))

    # Always mark the selected object's world bounds and model-space origin.
    if snapshot.primitive_traces:
        bounds = snapshot.primitive_traces[0].world_bounds
        pen = QPen(QColor("#FFFFFF")); pen.setWidthF(1.0); pen.setStyle(Qt.DashLine)
        pen.setCosmetic(True); painter.setPen(pen); painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(bounds[0], bounds[1], bounds[2] - bounds[0],
                                bounds[3] - bounds[1]))
        origin = _map_point((0.0, 0.0), snapshot.primitive_traces[0].model_matrix)
        painter.drawLine(QPointF(origin[0] - 8, origin[1]), QPointF(origin[0] + 8, origin[1]))
        painter.drawLine(QPointF(origin[0], origin[1] - 8), QPointF(origin[0], origin[1] + 8))
    painter.restore()
