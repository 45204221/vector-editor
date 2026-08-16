"""Renderer-neutral geometry compilation and per-shape command caching."""

from dataclasses import dataclass
from enum import Enum
import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .rendering import RenderDelta, RenderDirtyFlag, RenderSnapshot


Point = Tuple[float, float]
Transform = Tuple[float, float, float, float, float, float]
Bounds = Tuple[float, float, float, float]


class PrimitiveTopology(str, Enum):
    TRIANGLE_FAN = "triangle_fan"
    LINE_LOOP = "line_loop"
    LINE_STRIP = "line_strip"
    LINES = "lines"
    TEXT = "text"


@dataclass(frozen=True)
class RenderMaterial:
    stroke_color: str
    fill_color: str
    line_width: float
    opacity: float
    pen_style: int
    brush_style: int
    line_join: str
    line_cap: str


@dataclass(frozen=True)
class RenderPrimitive:
    shape_id: str
    render_pass: int
    topology: PrimitiveTopology
    vertices: Tuple[Point, ...]
    transform: Transform
    material: RenderMaterial
    text: Optional[str] = None
    font_size: float = 0.0
    fill_from_stroke: bool = False
    world_bounds: Bounds = (0.0, 0.0, 0.0, 0.0)
    visible: bool = True


def _map_point(point: Point, transform: Transform) -> Point:
    x, y = float(point[0]), float(point[1])
    m11, m12, m21, m22, dx, dy = transform
    return m11 * x + m21 * y + dx, m12 * x + m22 * y + dy


def _world_bounds(vertices: Iterable[Point], transform: Transform,
                  padding: float = 0.0) -> Bounds:
    mapped = tuple(_map_point(point, transform) for point in vertices)
    if not mapped:
        return 0.0, 0.0, 0.0, 0.0
    xs, ys = zip(*mapped)
    return (min(xs) - padding, min(ys) - padding,
            max(xs) + padding, max(ys) + padding)


def _bounds_intersect(bounds: Bounds, viewport: Bounds) -> bool:
    return not (bounds[2] < viewport[0] or bounds[0] > viewport[2]
                or bounds[3] < viewport[1] or bounds[1] > viewport[3])


def _rect_points(rect: Dict[str, Any]) -> Tuple[Point, ...]:
    x, y = float(rect["x"]), float(rect["y"])
    width, height = float(rect["width"]), float(rect["height"])
    return ((x, y), (x + width, y), (x + width, y + height), (x, y + height))


def _ellipse_points(rect: Dict[str, Any], segments: int) -> Tuple[Point, ...]:
    x, y = float(rect["x"]), float(rect["y"])
    rx, ry = float(rect["width"]) / 2.0, float(rect["height"]) / 2.0
    cx, cy = x + rx, y + ry
    return tuple((cx + math.cos(index * math.tau / segments) * rx,
                  cy + math.sin(index * math.tau / segments) * ry)
                 for index in range(segments))


def _rounded_rect_points(rect: Dict[str, Any], radius: float,
                         corner_segments: int = 5) -> Tuple[Point, ...]:
    x, y = float(rect["x"]), float(rect["y"])
    width, height = float(rect["width"]), float(rect["height"])
    radius = max(0.0, min(float(radius), width / 2.0, height / 2.0))
    if radius == 0:
        return _rect_points(rect)
    centers = ((x + width - radius, y + radius),
               (x + width - radius, y + height - radius),
               (x + radius, y + height - radius),
               (x + radius, y + radius))
    result = []
    for corner, center in enumerate(centers):
        start = -math.pi / 2 + corner * math.pi / 2
        for step in range(corner_segments + 1):
            angle = start + step * math.pi / (2 * corner_segments)
            result.append((center[0] + math.cos(angle) * radius,
                           center[1] + math.sin(angle) * radius))
    return tuple(result)


class GeometryCompiler:
    """Compile serialized shapes into API-neutral draw primitives."""

    def __init__(self, curve_segments: int = 32):
        self.curve_segments = max(8, int(curve_segments))
        self.compile_count = 0

    def compile_shape(self, shape: Dict[str, Any]) -> Tuple[RenderPrimitive, ...]:
        self.compile_count += 1
        effective_visible = shape.get("effective_visible", shape.get("visible", True))

        shape_type = shape.get("type")
        style = shape.get("style", {})
        material = RenderMaterial(
            stroke_color=style.get("pen_color", "#000000"),
            fill_color=style.get("brush_color", "#FFFFFF"),
            line_width=float(style.get("pen_width", 1.0)),
            opacity=float(style.get("opacity", 1.0)),
            pen_style=int(style.get("pen_style", 1)),
            brush_style=int(style.get("brush_style", 1)),
            line_join=style.get("line_join", "miter"),
            line_cap=style.get("line_cap", "butt"),
        )
        transform_data = shape.get("transform", {})
        transform = (
            float(transform_data.get("m11", 1.0)), float(transform_data.get("m12", 0.0)),
            float(transform_data.get("m21", 0.0)), float(transform_data.get("m22", 1.0)),
            float(transform_data.get("dx", 0.0)), float(transform_data.get("dy", 0.0)),
        )
        shape_id = shape["id"]

        def primitive(topology, vertices, text=None, font_size=0.0, render_pass=None,
                      fill_from_stroke=False):
            if render_pass is None:
                render_pass = 1 if topology == PrimitiveTopology.TRIANGLE_FAN else 2
            vertices = tuple(vertices)
            # GPU stroke adds a one-pixel coverage fringe outside the opaque body.
            padding = material.line_width / 2.0 + 1.0 if render_pass == 2 else 0.0
            return RenderPrimitive(shape_id, render_pass, topology, vertices, transform,
                                   material, text, float(font_size), fill_from_stroke,
                                   _world_bounds(vertices, transform, padding),
                                   effective_visible)

        if shape_type in ("rectangle", "rounded_rect", "org_node"):
            if shape_type == "rounded_rect":
                points = _rounded_rect_points(shape["rect"], shape.get("radius", 20))
            elif shape_type == "org_node":
                points = _rounded_rect_points(shape["rect"], 8)
            else:
                points = _rect_points(shape["rect"])
            return (primitive(PrimitiveTopology.TRIANGLE_FAN, points),
                    primitive(PrimitiveTopology.LINE_LOOP, points))
        if shape_type == "ellipse":
            ring = _ellipse_points(shape["rect"], self.curve_segments)
            center = ((sum(point[0] for point in ring) / len(ring),
                       sum(point[1] for point in ring) / len(ring)),)
            return (primitive(PrimitiveTopology.TRIANGLE_FAN, center + ring + ring[:1]),
                    primitive(PrimitiveTopology.LINE_LOOP, ring))
        if shape_type == "line":
            line = shape["line"]
            return (primitive(PrimitiveTopology.LINES,
                              ((line["x1"], line["y1"]), (line["x2"], line["y2"]))),)
        if shape_type in ("polygon", "polyline"):
            points = tuple((point["x"], point["y"]) for point in shape.get("points", ()))
            if shape_type == "polygon":
                return (primitive(PrimitiveTopology.TRIANGLE_FAN, points),
                        primitive(PrimitiveTopology.LINE_LOOP, points))
            return (primitive(PrimitiveTopology.LINE_STRIP, points),)
        if shape_type in ("diamond", "parallelogram"):
            rect = shape["rect"]
            corners = _rect_points(rect)
            if shape_type == "diamond":
                x, y = float(rect["x"]), float(rect["y"])
                width, height = float(rect["width"]), float(rect["height"])
                points = ((x + width / 2, y), (x + width, y + height / 2),
                          (x + width / 2, y + height), (x, y + height / 2))
            else:
                skew = float(rect["width"]) * float(shape.get("skew", 0.2))
                points = ((corners[0][0] + skew, corners[0][1]), corners[1],
                          (corners[2][0] - skew, corners[2][1]), corners[3])
            return (primitive(PrimitiveTopology.TRIANGLE_FAN, points),
                    primitive(PrimitiveTopology.LINE_LOOP, points))
        if shape_type == "connection":
            points = tuple(tuple(point) for point in shape.get("routed_points", ()))
            if not points:
                points = tuple(tuple(point) for point in shape.get("endpoint_points", ()))
            if len(points) < 2:
                return ()
            endpoints = tuple(tuple(point) for point in shape.get("endpoint_points", points[-2:]))
            first, last = endpoints[0], endpoints[-1]
            angle = math.atan2(last[1] - first[1], last[0] - first[0])
            arrow_length, arrow_angle = 12.0, math.radians(25)
            arrow = (last,
                     (last[0] - arrow_length * math.cos(angle - arrow_angle),
                      last[1] - arrow_length * math.sin(angle - arrow_angle)),
                     (last[0] - arrow_length * math.cos(angle + arrow_angle),
                      last[1] - arrow_length * math.sin(angle + arrow_angle)))
            return (primitive(PrimitiveTopology.LINE_STRIP, points),
                    primitive(PrimitiveTopology.TRIANGLE_FAN, arrow, render_pass=2,
                              fill_from_stroke=True))
        if shape_type == "text":
            return (primitive(PrimitiveTopology.TEXT, _rect_points(shape["rect"]),
                              shape.get("text", ""), shape.get("font_size", 16)),)
        if shape_type in {"resistor", "capacitor", "inductor", "ground", "battery", "diode"}:
            return self._compile_symbol(shape_type, shape["rect"], primitive)
        return ()

    def _compile_symbol(self, shape_type, rect, primitive):
        x, y = float(rect["x"]), float(rect["y"])
        width, height = float(rect["width"]), float(rect["height"])
        right, bottom, cx, cy = x + width, y + height, x + width / 2, y + height / 2
        if shape_type == "resistor":
            count = max(int(width / 10), 2)
            points = [(x, cy)]
            for index in range(1, count):
                points.append((x + index * width / count,
                               cy + (height / 3 if index % 2 else -height / 3)))
            points.append((right, cy))
            return (primitive(PrimitiveTopology.LINE_STRIP, points),)
        if shape_type == "capacitor":
            gap = width * 0.15
            points = ((x, cy), (cx - gap, cy), (cx - gap, y), (cx - gap, bottom),
                      (cx + gap, y), (cx + gap, bottom), (cx + gap, cy), (right, cy))
            return (primitive(PrimitiveTopology.LINES, points),)
        if shape_type == "ground":
            top_y = y + height * 0.15
            points = [(cx, y), (cx, top_y)]
            for index, scale in enumerate((1.0, 0.6, 0.3)):
                line_y = top_y + (bottom - top_y) * (index + 1) / 4
                half = width * scale / 2
                points.extend(((cx - half, line_y), (cx + half, line_y)))
            return (primitive(PrimitiveTopology.LINES, points),)
        if shape_type == "battery":
            gap = width * 0.12
            points = ((x, cy), (cx - gap * 3, cy), (cx - gap * 3, y + 2), (cx - gap * 3, bottom - 2),
                      (cx - gap, y + 4), (cx - gap, bottom - 4), (cx + gap, y + 4), (cx + gap, bottom - 4),
                      (cx + gap * 3, y + 2), (cx + gap * 3, bottom - 2), (cx + gap * 3, cy), (right, cy))
            return (primitive(PrimitiveTopology.LINES, points),)
        if shape_type == "diode":
            triangle_width = height * 0.6
            start = cx - triangle_width / 2
            triangle = ((start, y), (start, bottom), (start + triangle_width, cy))
            bar_x = start + triangle_width + 2
            lines = ((x, cy), (start, cy), (bar_x, y), (bar_x, bottom), (bar_x, cy), (right, cy))
            return (primitive(PrimitiveTopology.TRIANGLE_FAN, triangle),
                    primitive(PrimitiveTopology.LINE_LOOP, triangle),
                    primitive(PrimitiveTopology.LINES, lines))
        # Inductor: sampled upper half-circles plus two leads.
        loops = 4
        radius = width / (loops * 2 + 2)
        points: List[Point] = [(x, cy), (x + radius, cy)]
        for loop in range(loops):
            loop_cx = x + radius + radius * (2 * loop + 1)
            for step in range(9):
                angle = math.pi * step / 8
                points.append((loop_cx - math.cos(angle) * radius,
                               cy - math.sin(angle) * height / 2))
        points.append((right, cy))
        return (primitive(PrimitiveTopology.LINE_STRIP, points),)


class GeometryCache:
    """Own compiled primitives and update only IDs present in RenderDelta."""

    def __init__(self, compiler: Optional[GeometryCompiler] = None):
        self.compiler = compiler or GeometryCompiler()
        self.revision = -1
        self._by_shape: Dict[str, Tuple[RenderPrimitive, ...]] = {}
        self._ordered_shape_ids: Tuple[str, ...] = ()

    def sync_snapshot(self, snapshot: RenderSnapshot) -> None:
        self._by_shape = {shape["id"]: self.compiler.compile_shape(shape)
                          for shape in snapshot.shapes}
        self._ordered_shape_ids = snapshot.ordered_shape_ids
        self.revision = snapshot.revision

    def apply_delta(self, delta: RenderDelta) -> None:
        if delta.full_sync:
            self._by_shape.clear()
        for shape_id in delta.removed_shape_ids:
            self._by_shape.pop(shape_id, None)
        for shape in delta.upserted_shapes:
            self._by_shape[shape["id"]] = self.compiler.compile_shape(shape)
        order_changed = bool(delta.dirty_flags & int(RenderDirtyFlag.ORDER | RenderDirtyFlag.VISIBILITY))
        if delta.full_sync or order_changed:
            self._ordered_shape_ids = delta.ordered_shape_ids
        self.revision = delta.revision

    def primitives(self, viewport: Optional[Bounds] = None) -> Tuple[RenderPrimitive, ...]:
        return tuple(primitive for _, _, primitive in self.primitive_items(viewport))

    def primitive_items(self, viewport: Optional[Bounds] = None):
        """Yield stable shape/primitive keys in render order without copying geometry."""
        for render_pass in (1, 2):
            for shape_id in self._ordered_shape_ids:
                for primitive_index, primitive in enumerate(self._by_shape.get(shape_id, ())):
                    if primitive.render_pass != render_pass:
                        continue
                    if not primitive.visible:
                        continue
                    if viewport is not None and not _bounds_intersect(
                            primitive.world_bounds, viewport):
                        continue
                    yield shape_id, primitive_index, primitive

    def primitives_for_shape(self, shape_id: str) -> Tuple[RenderPrimitive, ...]:
        return self._by_shape.get(shape_id, ())

    @property
    def ordered_shape_ids(self) -> Tuple[str, ...]:
        return self._ordered_shape_ids

    @property
    def shape_count(self) -> int:
        return len(self._by_shape)
