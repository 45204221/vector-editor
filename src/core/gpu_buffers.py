"""Stable, OpenGL/C++ friendly vertex buffer layout built from geometry commands."""

from dataclasses import dataclass
from enum import Enum
import struct
from typing import List, Optional, Tuple

from .geometry import (Bounds, GeometryCache, Point, PrimitiveTopology,
                       RenderPrimitive, Transform, _map_point)
from .native_geometry import (tessellate_segments_coverage,
                              tessellate_stroke_coverage)


VERTEX_COMPONENTS = ("x", "y", "r", "g", "b", "a")
VERTEX_STRIDE_FLOATS = len(VERTEX_COMPONENTS)
VERTEX_STRIDE_BYTES = VERTEX_STRIDE_FLOATS * 4


class GpuTopology(str, Enum):
    TRIANGLES = "triangles"
    LINES = "lines"


class GpuCommandKind(str, Enum):
    BATCH = "batch"
    TEXT = "text"


class GpuUploadKind(str, Enum):
    NONE = "none"
    FULL = "full"
    PARTIAL = "partial"


@dataclass(frozen=True)
class GpuDrawBatch:
    render_pass: int
    topology: GpuTopology
    first_vertex: int
    vertex_count: int
    line_width: float
    shape_ids: Tuple[str, ...]


@dataclass(frozen=True)
class GpuTextCommand:
    shape_id: str
    bounds: Bounds
    local_rect: Tuple[Point, ...]
    transform: Transform
    color: Tuple[float, float, float, float]
    text: str
    font_size: float


@dataclass(frozen=True)
class GpuCommandRef:
    kind: GpuCommandKind
    index: int


@dataclass(frozen=True)
class GpuBufferFrame:
    revision: int
    viewport: Optional[Bounds]
    vertices: Tuple[float, ...]
    batches: Tuple[GpuDrawBatch, ...]
    text_commands: Tuple[GpuTextCommand, ...]
    command_stream: Tuple[GpuCommandRef, ...]
    source_primitive_count: int

    def vertex_bytes(self) -> bytes:
        """Return a deterministic little-endian float32 payload for a native VBO."""
        if not self.vertices:
            return b""
        return struct.pack("<{}f".format(len(self.vertices)), *self.vertices)

    def vertex_range_bytes(self, first_vertex: int, vertex_count: int) -> bytes:
        first = first_vertex * VERTEX_STRIDE_FLOATS
        last = (first_vertex + vertex_count) * VERTEX_STRIDE_FLOATS
        values = self.vertices[first:last]
        return struct.pack("<{}f".format(len(values)), *values) if values else b""

    @property
    def vertex_count(self) -> int:
        return len(self.vertices) // VERTEX_STRIDE_FLOATS


@dataclass(frozen=True)
class GpuUploadRange:
    first_vertex: int
    vertex_count: int
    byte_offset: int
    payload: bytes


@dataclass(frozen=True)
class GpuUploadPlan:
    kind: GpuUploadKind
    ranges: Tuple[GpuUploadRange, ...]
    changed_vertex_count: int

    @property
    def byte_count(self) -> int:
        return sum(len(item.payload) for item in self.ranges)


def plan_gpu_upload(previous: Optional[GpuBufferFrame], current: GpuBufferFrame,
                    full_upload_threshold: float = 0.35) -> GpuUploadPlan:
    """Plan an allocation or vertex-aligned sub-buffer writes for the current frame."""
    if previous is None or previous.vertex_count != current.vertex_count:
        payload = current.vertex_bytes()
        ranges = ((GpuUploadRange(0, current.vertex_count, 0, payload),)
                  if current.vertex_count else ())
        return GpuUploadPlan(GpuUploadKind.FULL, ranges, current.vertex_count)
    if previous.vertices == current.vertices:
        return GpuUploadPlan(GpuUploadKind.NONE, (), 0)

    changed = []
    stride = VERTEX_STRIDE_FLOATS
    for vertex in range(current.vertex_count):
        start = vertex * stride
        if previous.vertices[start:start + stride] != current.vertices[start:start + stride]:
            changed.append(vertex)
    if not changed:
        return GpuUploadPlan(GpuUploadKind.NONE, (), 0)
    if len(changed) / max(1, current.vertex_count) >= full_upload_threshold:
        payload = current.vertex_bytes()
        return GpuUploadPlan(
            GpuUploadKind.FULL,
            (GpuUploadRange(0, current.vertex_count, 0, payload),),
            len(changed),
        )

    groups = []
    first = previous_vertex = changed[0]
    for vertex in changed[1:]:
        if vertex != previous_vertex + 1:
            groups.append((first, previous_vertex - first + 1))
            first = vertex
        previous_vertex = vertex
    groups.append((first, previous_vertex - first + 1))
    ranges = tuple(GpuUploadRange(first_vertex, vertex_count,
                                  first_vertex * VERTEX_STRIDE_BYTES,
                                  current.vertex_range_bytes(first_vertex, vertex_count))
                   for first_vertex, vertex_count in groups)
    return GpuUploadPlan(GpuUploadKind.PARTIAL, ranges, len(changed))


def _color_rgba(value: str, alpha: float) -> Tuple[float, float, float, float]:
    text = str(value or "#000000").lstrip("#")
    if len(text) == 3:
        text = "".join(character * 2 for character in text)
    if len(text) == 8:
        color_alpha = int(text[:2], 16) / 255.0
        text = text[2:]
    else:
        color_alpha = 1.0
    if len(text) != 6:
        text = "000000"
    return (int(text[0:2], 16) / 255.0,
            int(text[2:4], 16) / 255.0,
            int(text[4:6], 16) / 255.0,
            max(0.0, min(1.0, float(alpha) * color_alpha)))


def _expanded_geometry(primitive: RenderPrimitive):
    topology = primitive.topology
    if topology == PrimitiveTopology.TRIANGLE_FAN:
        points = tuple(_map_point(point, primitive.transform) for point in primitive.vertices)
        if len(points) < 3:
            return GpuTopology.TRIANGLES, ()
        triangles = []
        for index in range(1, len(points) - 1):
            triangles.extend((points[0], points[index], points[index + 1]))
        return GpuTopology.TRIANGLES, tuple(triangles)
    if topology == PrimitiveTopology.LINE_LOOP:
        triangles = tessellate_stroke_coverage(
            primitive.vertices, primitive.material.line_width, closed=True,
            join=primitive.material.line_join, cap=primitive.material.line_cap)
        return GpuTopology.TRIANGLES, tuple(
            (*_map_point(point[:2], primitive.transform), point[2])
            for point in triangles)
    if topology == PrimitiveTopology.LINE_STRIP:
        triangles = tessellate_stroke_coverage(
            primitive.vertices, primitive.material.line_width,
            join=primitive.material.line_join, cap=primitive.material.line_cap)
        return GpuTopology.TRIANGLES, tuple(
            (*_map_point(point[:2], primitive.transform), point[2])
            for point in triangles)
    if topology == PrimitiveTopology.LINES:
        triangles = tessellate_segments_coverage(
            primitive.vertices, primitive.material.line_width,
            cap=primitive.material.line_cap)
        return GpuTopology.TRIANGLES, tuple(
            (*_map_point(point[:2], primitive.transform), point[2])
            for point in triangles)
    return None, ()


def gpu_text_command(primitive: RenderPrimitive) -> GpuTextCommand:
    return GpuTextCommand(
        primitive.shape_id,
        primitive.world_bounds,
        primitive.vertices,
        primitive.transform,
        _color_rgba(primitive.material.stroke_color, 1.0),
        primitive.text or "",
        primitive.font_size,
    )


def encode_gpu_primitive(primitive: RenderPrimitive):
    """Return topology, line width and interleaved float vertices for one vector primitive."""
    topology, points = _expanded_geometry(primitive)
    if not points:
        return topology, 0.0, ()
    is_fill = primitive.topology == PrimitiveTopology.TRIANGLE_FAN
    color_name = (primitive.material.stroke_color
                  if primitive.fill_from_stroke or not is_fill
                  else primitive.material.fill_color)
    alpha = primitive.material.opacity if primitive.render_pass == 1 else 1.0
    color = _color_rgba(color_name, alpha)
    vertices = []
    for point in points:
        x, y = point[:2]
        coverage = point[2] if len(point) > 2 else 1.0
        vertex_color = (*color[:3], color[3] * coverage)
        vertices.extend((float(x), float(y), *vertex_color))
    line_width = primitive.material.line_width if topology == GpuTopology.LINES else 0.0
    return topology, line_width, tuple(vertices)


class GpuBufferBuilder:
    """Flatten visible primitives into batches without depending on an OpenGL context."""

    def build(self, cache: GeometryCache, viewport: Optional[Bounds] = None) -> GpuBufferFrame:
        primitives = cache.primitives(viewport)
        vertices: List[float] = []
        batch_records = []
        text_commands = []
        command_stream = []

        for primitive in primitives:
            if primitive.topology == PrimitiveTopology.TEXT:
                text_commands.append(gpu_text_command(primitive))
                command_stream.append(GpuCommandRef(GpuCommandKind.TEXT,
                                                    len(text_commands) - 1))
                continue
            topology, line_width, encoded_vertices = encode_gpu_primitive(primitive)
            if not encoded_vertices:
                continue
            first_vertex = len(vertices) // VERTEX_STRIDE_FLOATS
            vertices.extend(encoded_vertices)
            vertex_count = len(encoded_vertices) // VERTEX_STRIDE_FLOATS
            key = (primitive.render_pass, topology, line_width)
            last_is_current_batch = (command_stream
                                     and command_stream[-1].kind == GpuCommandKind.BATCH
                                     and command_stream[-1].index == len(batch_records) - 1)
            if batch_records and last_is_current_batch and batch_records[-1]["key"] == key:
                batch_records[-1]["vertex_count"] += vertex_count
                if primitive.shape_id not in batch_records[-1]["shape_ids"]:
                    batch_records[-1]["shape_ids"].append(primitive.shape_id)
            else:
                batch_records.append({
                    "key": key,
                    "render_pass": primitive.render_pass,
                    "topology": topology,
                    "first_vertex": first_vertex,
                    "vertex_count": vertex_count,
                    "line_width": line_width,
                    "shape_ids": [primitive.shape_id],
                })
                command_stream.append(GpuCommandRef(GpuCommandKind.BATCH,
                                                    len(batch_records) - 1))

        batches = tuple(GpuDrawBatch(record["render_pass"], record["topology"],
                                     record["first_vertex"], record["vertex_count"],
                                     record["line_width"], tuple(record["shape_ids"]))
                        for record in batch_records)
        return GpuBufferFrame(cache.revision, viewport, tuple(vertices), batches,
                              tuple(text_commands), tuple(command_stream), len(primitives))
