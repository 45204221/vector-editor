"""可替换渲染后端与渲染数据接口。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import IntFlag
from typing import Any, Dict, Tuple

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QBrush, QFont, QPainter, QPainterPath, QPen, QPolygonF, QTransform

from .collision import ColliderType


def _draw_grid(painter, canvas, viewport):
    pen = QPen(QColor(220, 220, 220)); pen.setWidth(1)
    painter.setPen(pen); painter.setBrush(Qt.NoBrush)
    start_x = max(0, int(viewport.left()) // canvas.grid_size * canvas.grid_size)
    end_x = min(int(canvas.width), int(viewport.right()) + canvas.grid_size)
    start_y = max(0, int(viewport.top()) // canvas.grid_size * canvas.grid_size)
    end_y = min(int(canvas.height), int(viewport.bottom()) + canvas.grid_size)
    for x in range(start_x, end_x + 1, canvas.grid_size):
        painter.drawLine(x, 0, x, int(canvas.height))
    for y in range(start_y, end_y + 1, canvas.grid_size):
        painter.drawLine(0, y, int(canvas.width), y)


def _draw_engine_debug(painter, canvas, visible_shapes):
    painter.save()
    for shape in visible_shapes:
        collider = getattr(shape, "collider", None)
        if not collider or not collider.enabled or collider.type == ColliderType.NONE:
            continue
        pen = QPen(QColor("#E53935") if shape.is_colliding else QColor("#00A67D"))
        pen.setStyle(Qt.DashLine); pen.setWidth(1)
        painter.setPen(pen); painter.setBrush(Qt.NoBrush)
        rect = collider.bounds(shape)
        if collider.type == ColliderType.CIRCLE:
            radius = collider.effective_radius(shape)
            painter.drawEllipse(rect.center(), radius, radius)
        else:
            painter.drawRect(rect)
        body = shape.rigid_body
        if body.enabled:
            center = rect.center()
            painter.drawLine(center, QPointF(center.x() + body.velocity_x * .15,
                                              center.y() + body.velocity_y * .15))
    by_id = {shape.id: shape for shape in canvas.shapes}
    for spring in canvas.physics_world.springs:
        if spring.first_id in by_id and spring.second_id in by_id:
            pen = QPen(QColor("#7E57C2")); pen.setStyle(Qt.DotLine); painter.setPen(pen)
            painter.drawLine(by_id[spring.first_id].bounding_rect().center(),
                             by_id[spring.second_id].bounding_rect().center())
    painter.restore()


class RenderDirtyFlag(IntFlag):
    NONE = 0
    GEOMETRY = 1
    STYLE = 2
    TRANSFORM = 4
    ORDER = 8
    VISIBILITY = 16
    DEBUG = 32
    ALL = GEOMETRY | STYLE | TRANSFORM | ORDER | VISIBILITY | DEBUG


@dataclass(frozen=True)
class RenderSnapshot:
    """面向 OpenGL/C++ 的纯数据快照，不包含 QPainter 或 GPU 对象。"""
    revision: int
    width: float
    height: float
    grid_size: int
    show_grid: bool
    ordered_shape_ids: Tuple[str, ...]
    shapes: Tuple[Dict[str, Any], ...]


@dataclass(frozen=True)
class RenderDelta:
    """一次文档变更的批量增量，可直接映射到 GPU Buffer 更新。"""
    revision: int
    dirty_flags: int
    upserted_shapes: Tuple[Dict[str, Any], ...]
    removed_shape_ids: Tuple[str, ...]
    ordered_shape_ids: Tuple[str, ...]
    full_sync: bool = False


class RenderBackend(ABC):
    requires_snapshot = False
    uses_render_delta = False

    @abstractmethod
    def sync_document(self, document, dirty_flags: RenderDirtyFlag):
        pass

    @abstractmethod
    def render(self, painter: QPainter, viewport: QRectF = None):
        pass

    def release(self):
        pass


class QPainterBackend(RenderBackend):
    """兼容现有视觉结果的 CPU/QPainter 后端。"""

    def __init__(self):
        self.canvas = None
        self.last_total_shapes = 0
        self.last_visible_shapes = 0

    def sync_document(self, document, dirty_flags):
        self.canvas = document

    def render(self, painter, viewport=None):
        canvas = self.canvas
        if canvas is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(QRectF(0, 0, canvas.width, canvas.height), QColor(255, 255, 255))
        viewport = (viewport or QRectF(0, 0, canvas.width, canvas.height)).intersected(
            QRectF(0, 0, canvas.width, canvas.height))
        if canvas.show_grid:
            _draw_grid(painter, canvas, viewport)
        all_shapes = canvas.sorted_shapes()
        shapes = [shape for shape in all_shapes if shape.bounding_rect().intersects(viewport)]
        self.last_total_shapes = len(all_shapes)
        self.last_visible_shapes = len(shapes)
        for pass_type in (1, 2):
            for shape in shapes:
                try:
                    shape.paint(painter, pass_type=pass_type)
                except Exception as error:
                    print(f"[ERROR] render {shape.shape_type}: {error}")
        if canvas.show_engine_debug:
            _draw_engine_debug(painter, canvas, shapes)
        painter.restore()


class CommandQPainterBackend(RenderBackend):
    """Reference renderer for validating the RenderDelta/GeometryCache pipeline."""

    uses_render_delta = True

    def __init__(self, canvas):
        # Lazy import avoids a module cycle: geometry consumes RenderDelta types.
        from .geometry import GeometryCache, PrimitiveTopology
        self.canvas = canvas
        self.cache = GeometryCache()
        self.topology = PrimitiveTopology
        self.last_primitive_count = 0

    def sync_document(self, document, dirty_flags):
        with self.canvas.profiler.measure("geometry"):
            self.cache.apply_delta(document)

    def render(self, painter, viewport=None):
        canvas = self.canvas
        viewport = (viewport or QRectF(0, 0, canvas.width, canvas.height)).intersected(
            QRectF(0, 0, canvas.width, canvas.height))
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(QRectF(0, 0, canvas.width, canvas.height), QColor(255, 255, 255))
        if canvas.show_grid:
            _draw_grid(painter, canvas, viewport)
        viewport_bounds = (viewport.left(), viewport.top(), viewport.right(), viewport.bottom())
        primitives = self.cache.primitives(viewport_bounds)
        self.last_primitive_count = len(primitives)
        for primitive in primitives:
            self._draw_primitive(painter, primitive)
        self._draw_selection_overlay(painter)
        if canvas.show_engine_debug:
            visible = [shape for shape in canvas.sorted_shapes()
                       if shape.bounding_rect().intersects(viewport)]
            _draw_engine_debug(painter, canvas, visible)
        painter.restore()

    def _draw_primitive(self, painter, primitive):
        topology = primitive.topology
        vertices = primitive.vertices
        if not vertices:
            return
        material = primitive.material
        transform = primitive.transform
        painter.save()
        painter.setTransform(QTransform(transform[0], transform[1], transform[2],
                                        transform[3], transform[4], transform[5]), True)
        pen = QPen(QColor(material.stroke_color))
        pen.setWidthF(material.line_width)
        pen.setStyle(Qt.PenStyle(material.pen_style))
        pen.setJoinStyle({"miter": Qt.MiterJoin, "bevel": Qt.BevelJoin,
                          "round": Qt.RoundJoin}.get(material.line_join, Qt.MiterJoin))
        pen.setCapStyle({"butt": Qt.FlatCap, "square": Qt.SquareCap,
                         "round": Qt.RoundCap}.get(material.line_cap, Qt.FlatCap))
        fill_color = material.stroke_color if primitive.fill_from_stroke else material.fill_color
        brush = QBrush(QColor(fill_color))
        brush.setStyle(Qt.BrushStyle(material.brush_style))
        points = [QPointF(float(point[0]), float(point[1])) for point in vertices]
        if topology == self.topology.TRIANGLE_FAN:
            painter.setPen(Qt.NoPen)
            painter.setBrush(brush)
            painter.setOpacity(material.opacity if primitive.render_pass == 1 else 1.0)
            painter.drawPolygon(QPolygonF(points))
        elif topology == self.topology.LINE_LOOP:
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.setOpacity(1.0)
            painter.drawPolygon(QPolygonF(points))
        elif topology == self.topology.LINE_STRIP:
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.setOpacity(1.0)
            path = QPainterPath(points[0])
            for point in points[1:]:
                path.lineTo(point)
            painter.drawPath(path)
        elif topology == self.topology.LINES:
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.setOpacity(1.0)
            for first, second in zip(points[::2], points[1::2]):
                painter.drawLine(first, second)
        elif topology == self.topology.TEXT:
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            font = QFont(painter.font())
            font.setPointSizeF(primitive.font_size)
            painter.setFont(font)
            rect = QRectF(points[0], points[2]).normalized()
            painter.drawText(rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                             primitive.text or "")
        painter.restore()

    def _draw_selection_overlay(self, painter):
        selected = [shape for shape in self.canvas.get_selected_shapes()
                    if self.canvas.layer_manager.is_shape_visible(shape)]
        if not selected:
            return
        painter.save()
        pen = QPen(QColor("#0078D4")); pen.setWidth(1); pen.setStyle(Qt.DashLine)
        painter.setPen(pen); painter.setBrush(Qt.NoBrush)
        for shape in selected:
            rect = shape.bounding_rect()
            painter.drawRect(rect)
            for point in (rect.topLeft(), rect.topRight(), rect.bottomRight(), rect.bottomLeft()):
                painter.drawRect(QRectF(point.x() - 3, point.y() - 3, 6, 6))
        painter.restore()
