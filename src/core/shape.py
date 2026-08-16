"""图形基类和具体图形实现"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
from enum import Enum
import json
import math
from uuid import uuid4

from PyQt5.QtCore import QPointF, QRectF, QLineF, Qt, QVariant
from PyQt5.QtGui import QPen, QBrush, QColor, QPainter, QPainterPath, QTransform, QFont
from .collision import Collider, ColliderType
from .physics import RigidBody


class ShapeType(Enum):
    """图形类型枚举"""

    RECTANGLE = "rectangle"
    ELLIPSE = "ellipse"
    LINE = "line"
    POLYGON = "polygon"
    POLYLINE = "polyline"
    DIAMOND = "diamond"
    ROUNDED_RECT = "rounded_rect"
    PARALLELOGRAM = "parallelogram"
    RESISTOR = "resistor"
    CAPACITOR = "capacitor"
    INDUCTOR = "inductor"
    GROUND = "ground"
    BATTERY = "battery"
    DIODE = "diode"
    ORG_NODE = "org_node"
    CONNECTION = "connection"
    TEXT = "text"
    CUSTOM = "custom"


@dataclass
class ShapeStyle:
    """图形样式"""

    pen_color: str = "#000000"
    pen_width: float = 1.0
    pen_style: int = Qt.SolidLine
    brush_color: str = "#FFFFFF"
    brush_style: int = Qt.SolidPattern
    opacity: float = 1.0
    line_join: str = "miter"
    line_cap: str = "butt"


class Shape(ABC):
    """图形基类"""

    def __init__(self, shape_type: ShapeType, style: Optional[ShapeStyle] = None):
        self.shape_type = shape_type
        self.style = style or ShapeStyle()
        self.selected = False
        self.visible = True
        self.transform = QTransform()
        self.parent = None
        self.children = []
        # 游戏引擎展示组件：与图形本体解耦，默认不会改变普通编辑行为。
        self.id = str(uuid4())
        self.layer_id = "content"
        self.z_index = 0
        self.collider = Collider(ColliderType.NONE if shape_type in (ShapeType.LINE, ShapeType.POLYLINE, ShapeType.CONNECTION) else ColliderType.AABB)
        self.rigid_body = RigidBody()
        self.is_colliding = False
        self.colliding_with = set()

    @abstractmethod
    def bounding_rect(self) -> QRectF:
        pass

    @abstractmethod
    def contains_point(self, point: QPointF) -> bool:
        pass

    @abstractmethod
    def paint(self, painter: QPainter, pass_type: int = 0) -> None:
        pass

    def move_by(self, dx: float, dy: float) -> None:
        if dx != 0 or dy != 0:
            self.translate(dx, dy)

    def _style_pen(self) -> QPen:
        pen = QPen(QColor(self.style.pen_color))
        pen.setWidthF(float(self.style.pen_width))
        pen.setStyle(Qt.PenStyle(self.style.pen_style))
        pen.setJoinStyle({"miter": Qt.MiterJoin, "bevel": Qt.BevelJoin,
                          "round": Qt.RoundJoin}.get(self.style.line_join, Qt.MiterJoin))
        pen.setCapStyle({"butt": Qt.FlatCap, "square": Qt.SquareCap,
                         "round": Qt.RoundCap}.get(self.style.line_cap, Qt.FlatCap))
        return pen

    def translate(self, dx: float, dy: float) -> None:
        self.transform.translate(dx, dy)
        for child in self.children:
            child.translate(dx, dy)

    def rotate(self, angle: float, center: QPointF) -> None:
        self.transform.translate(center.x(), center.y())
        self.transform.rotate(angle)
        self.transform.translate(-center.x(), -center.y())
        for child in self.children:
            child.rotate(angle, center)

    def scale(self, sx: float, sy: float, center: QPointF) -> None:
        self.transform.translate(center.x(), center.y())
        self.transform.scale(sx, sy)
        self.transform.translate(-center.x(), -center.y())
        for child in self.children:
            child.scale(sx, sy, center)

    def flip_horizontal(self, center_x: float) -> None:
        """水平翻转 — 子类重写"""

    def flip_vertical(self, center_y: float) -> None:
        """垂直翻转 — 子类重写"""

    def world_transform(self) -> QTransform:
        if self.parent:
            parent_transform = self.parent.world_transform()
            return parent_transform * self.transform
        return self.transform

    def map_to_scene(self, point: QPointF) -> QPointF:
        return self.transform.map(point)

    def map_from_scene(self, point: QPointF) -> QPointF:
        return self.world_transform().inverted()[0].map(point)

    def _local_anchors(self) -> List[QPointF]:
        """子类重写：返回局部坐标系中的锚点"""
        if hasattr(self, 'rect'):
            r = self.rect
            return [
                QPointF(r.x() + r.width() / 2, r.y()),              # 0: 上中点
                QPointF(r.x() + r.width(), r.y() + r.height() / 2), # 1: 右中点
                QPointF(r.x() + r.width() / 2, r.y() + r.height()), # 2: 下中点
                QPointF(r.x(), r.y() + r.height() / 2),             # 3: 左中点
                r.topLeft(), r.topRight(),                           # 4,5: 上角
                r.bottomRight(), r.bottomLeft(),                     # 6,7: 下角
            ]
        return []

    def get_anchor_points(self) -> List[QPointF]:
        """返回世界坐标系中的锚点列表"""
        local = self._local_anchors()
        wt = self.world_transform()
        return [wt.map(p) for p in local]

    def get_anchor_point(self, index: int) -> QPointF:
        pts = self.get_anchor_points()
        if 0 <= index < len(pts):
            return pts[index]
        return QPointF()

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "type": self.shape_type.value,
            "style": asdict(self.style),
            "selected": self.selected,
            "visible": self.visible,
            "id": self.id,
            "layer_id": self.layer_id,
            "z_index": self.z_index,
            "collider": self.collider.to_dict(),
            "rigid_body": self.rigid_body.to_dict(),
            "transform": {
                "m11": self.transform.m11(),
                "m12": self.transform.m12(),
                "m21": self.transform.m21(),
                "m22": self.transform.m22(),
                "dx": self.transform.dx(),
                "dy": self.transform.dy(),
            },
        }
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any], preserve_id: bool = True) -> "Shape":
        """Restore a shape; clipboard clones must request a fresh identity."""
        shape_type = ShapeType(data["type"])

        if shape_type == ShapeType.RECTANGLE:
            shape = RectangleShape()
            r = data.get("rect", {})
            shape.rect = QRectF(r.get("x", 0), r.get("y", 0),
                                r.get("width", 100), r.get("height", 60))
        elif shape_type == ShapeType.ELLIPSE:
            shape = EllipseShape()
            r = data.get("rect", {})
            shape.rect = QRectF(r.get("x", 0), r.get("y", 0),
                                r.get("width", 100), r.get("height", 60))
        elif shape_type == ShapeType.LINE:
            shape = LineShape()
            ln = data.get("line", {})
            shape.line = (QPointF(ln.get("x1", 0), ln.get("y1", 0)),
                          QPointF(ln.get("x2", 100), ln.get("y2", 0)))
        elif shape_type == ShapeType.POLYGON:
            shape = PolygonShape()
            pts = data.get("points", [])
            shape.points = [QPointF(p["x"], p["y"]) for p in pts]
        elif shape_type == ShapeType.POLYLINE:
            shape = PolylineShape()
            pts = data.get("points", [])
            shape.points = [QPointF(p["x"], p["y"]) for p in pts]
        elif shape_type == ShapeType.DIAMOND:
            shape = DiamondShape()
            r = data.get("rect", {})
            shape.rect = QRectF(r.get("x", 0), r.get("y", 0),
                                r.get("width", 120), r.get("height", 80))
        elif shape_type == ShapeType.ROUNDED_RECT:
            shape = RoundedRectShape()
            r = data.get("rect", {})
            shape.rect = QRectF(r.get("x", 0), r.get("y", 0),
                                r.get("width", 120), r.get("height", 60))
        elif shape_type == ShapeType.PARALLELOGRAM:
            shape = ParallelogramShape()
            r = data.get("rect", {})
            shape.rect = QRectF(r.get("x", 0), r.get("y", 0),
                                r.get("width", 120), r.get("height", 60))
        elif shape_type == ShapeType.RESISTOR:
            shape = ResistorShape()
            r = data.get("rect", {})
            shape.rect = QRectF(r.get("x", 0), r.get("y", 0),
                                r.get("width", 120), r.get("height", 40))
        elif shape_type == ShapeType.CAPACITOR:
            shape = CapacitorShape()
            r = data.get("rect", {})
            shape.rect = QRectF(r.get("x", 0), r.get("y", 0),
                                r.get("width", 60), r.get("height", 40))
        elif shape_type == ShapeType.INDUCTOR:
            shape = InductorShape()
            r = data.get("rect", {})
            shape.rect = QRectF(r.get("x", 0), r.get("y", 0),
                                r.get("width", 100), r.get("height", 40))
        elif shape_type == ShapeType.GROUND:
            shape = GroundShape()
            r = data.get("rect", {})
            shape.rect = QRectF(r.get("x", 0), r.get("y", 0),
                                r.get("width", 60), r.get("height", 40))
        elif shape_type == ShapeType.BATTERY:
            shape = BatteryShape()
            r = data.get("rect", {})
            shape.rect = QRectF(r.get("x", 0), r.get("y", 0),
                                r.get("width", 60), r.get("height", 40))
        elif shape_type == ShapeType.DIODE:
            shape = DiodeShape()
            r = data.get("rect", {})
            shape.rect = QRectF(r.get("x", 0), r.get("y", 0),
                                r.get("width", 80), r.get("height", 40))
        elif shape_type == ShapeType.ORG_NODE:
            shape = OrgNodeShape()
            r = data.get("rect", {})
            shape.rect = QRectF(r.get("x", 0), r.get("y", 0),
                                r.get("width", 120), r.get("height", 50))
        elif shape_type == ShapeType.TEXT:
            shape = TextShape()
            shape.text = data.get("text", "文字")
            shape.font_size = data.get("font_size", 16)
            r = data.get("rect", {})
            shape.rect = QRectF(r.get("x", 0), r.get("y", 0),
                                r.get("width", 200), r.get("height", 40))
        elif shape_type == ShapeType.CONNECTION:
            shape = ConnectionShape()
            shape.source_anchor = data.get("source_anchor", 0)
            shape.target_anchor = data.get("target_anchor", 2)
            shape._source_index = data.get("source_index", -1)
            shape._target_index = data.get("target_index", -1)
        else:
            raise ValueError(f"未知的图形类型: {shape_type}")

        shape.selected = data.get("selected", False) if preserve_id else False
        shape.visible = data.get("visible", True)
        if preserve_id:
            shape.id = data.get("id", shape.id)
        shape.layer_id = data.get("layer_id", "content")
        shape.z_index = data.get("z_index", 0)
        shape.collider = Collider.from_dict(data.get("collider", {"type": shape.collider.type.value}))
        shape.rigid_body = RigidBody.from_dict(data.get("rigid_body", {}))

        transform_data = data.get("transform", {})
        shape.transform = QTransform(
            transform_data.get("m11", 1),
            transform_data.get("m12", 0),
            transform_data.get("m21", 0),
            transform_data.get("m22", 1),
            transform_data.get("dx", 0),
            transform_data.get("dy", 0),
        )

        if "style" in data:
            style_data = data["style"]
            shape.style = ShapeStyle(
                pen_color=style_data.get("pen_color", "#000000"),
                pen_width=style_data.get("pen_width", 1.0),
                pen_style=style_data.get("pen_style", Qt.SolidLine),
                brush_color=style_data.get("brush_color", "#FFFFFF"),
                brush_style=style_data.get("brush_style", Qt.SolidPattern),
                opacity=style_data.get("opacity", 1.0),
                line_join=style_data.get("line_join", "miter"),
                line_cap=style_data.get("line_cap", "butt"),
            )

        return shape


class RectangleShape(Shape):
    """矩形图形"""

    def __init__(
        self,
        x: float = 0,
        y: float = 0,
        width: float = 100,
        height: float = 60,
        style: Optional[ShapeStyle] = None,
    ):
        super().__init__(ShapeType.RECTANGLE, style)
        self.rect = QRectF(x, y, width, height)

    def bounding_rect(self) -> QRectF:
        if self.transform.isIdentity():
            return self.rect
        return self.transform.mapRect(self.rect)

    def contains_point(self, point: QPointF) -> bool:
        return self.rect.contains(point)

    def paint(self, painter: QPainter, pass_type: int = 0) -> None:
        if not self.visible:
            return

        painter.save()
        painter.setTransform(self.world_transform(), True)

        pen = self._style_pen()

        brush = QBrush(QColor(self.style.brush_color))
        brush.setStyle(self.style.brush_style)

        # 填充 pass
        if pass_type in (0, 1):
            painter.setPen(Qt.NoPen)
            painter.setBrush(brush)
            painter.setOpacity(self.style.opacity)
            painter.drawRect(self.rect)

        # 边框 pass
        if pass_type in (0, 2):
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.setOpacity(1.0)
            painter.drawRect(self.rect)

        # 选择框始终在边框 pass 绘制
        if self.selected and pass_type in (0, 2):
            self._draw_selection_box(painter)

        painter.restore()

    def _draw_selection_box(self, painter: QPainter) -> None:
        """绘制选择框"""
        pen = QPen(QColor("#0078D4"))
        pen.setWidth(1)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        # 绘制边界框
        painter.drawRect(self.rect)

        # 绘制调整大小的手柄
        handle_size = 6
        rect = self.rect
        handles = [
            # 四个角
            QPointF(rect.left(), rect.top()),
            QPointF(rect.right(), rect.top()),
            QPointF(rect.right(), rect.bottom()),
            QPointF(rect.left(), rect.bottom()),
            # 四条边的中点
            QPointF(rect.left() + rect.width() / 2, rect.top()),
            QPointF(rect.right(), rect.top() + rect.height() / 2),
            QPointF(rect.left() + rect.width() / 2, rect.bottom()),
            QPointF(rect.left(), rect.top() + rect.height() / 2),
        ]

        for handle in handles:
            painter.drawRect(
                QRectF(
                    handle.x() - handle_size / 2,
                    handle.y() - handle_size / 2,
                    handle_size,
                    handle_size,
                )
            )

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data["rect"] = {
            "x": self.rect.x(),
            "y": self.rect.y(),
            "width": self.rect.width(),
            "height": self.rect.height(),
        }
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RectangleShape":
        shape = super().from_dict(data)
        shape.rect = QRectF(
            data["rect"]["x"],
            data["rect"]["y"],
            data["rect"]["width"],
            data["rect"]["height"],
        )
        return shape

    def flip_horizontal(self, center_x: float) -> None:
        wr = self.bounding_rect()
        new_x = 2 * center_x - wr.x() - wr.width()
        self.rect = QRectF(new_x, wr.y(), wr.width(), wr.height())
        self.transform.reset()

    def flip_vertical(self, center_y: float) -> None:
        wr = self.bounding_rect()
        new_y = 2 * center_y - wr.y() - wr.height()
        self.rect = QRectF(wr.x(), new_y, wr.width(), wr.height())
        self.transform.reset()


class EllipseShape(Shape):
    """椭圆图形"""

    def __init__(
        self,
        x: float = 0,
        y: float = 0,
        width: float = 100,
        height: float = 60,
        style: Optional[ShapeStyle] = None,
    ):
        super().__init__(ShapeType.ELLIPSE, style)
        self.rect = QRectF(x, y, width, height)

    def bounding_rect(self) -> QRectF:
        if self.transform.isIdentity():
            return self.rect
        return self.transform.mapRect(self.rect)

    def contains_point(self, point: QPointF) -> bool:
        return self.rect.contains(point)

    def paint(self, painter: QPainter, pass_type: int = 0) -> None:
        if not self.visible:
            return

        painter.save()
        painter.setTransform(self.world_transform(), True)

        pen = self._style_pen()

        brush = QBrush(QColor(self.style.brush_color))
        brush.setStyle(self.style.brush_style)

        if pass_type in (0, 1):
            painter.setPen(Qt.NoPen)
            painter.setBrush(brush)
            painter.setOpacity(self.style.opacity)
            painter.drawEllipse(self.rect)

        if pass_type in (0, 2):
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.setOpacity(1.0)
            painter.drawEllipse(self.rect)

        if self.selected and pass_type in (0, 2):
            self._draw_selection_box(painter)

        painter.restore()

    def _draw_selection_box(self, painter: QPainter) -> None:
        """绘制选择框"""
        pen = QPen(QColor("#0078D4"))
        pen.setWidth(1)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.rect)

        # 绘制调整大小的手柄
        handle_size = 6
        rect = self.rect
        handles = [
            QPointF(rect.left(), rect.top()),
            QPointF(rect.right(), rect.top()),
            QPointF(rect.right(), rect.bottom()),
            QPointF(rect.left(), rect.bottom()),
        ]

        for handle in handles:
            painter.drawRect(
                QRectF(
                    handle.x() - handle_size / 2,
                    handle.y() - handle_size / 2,
                    handle_size,
                    handle_size,
                )
            )

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data["rect"] = {
            "x": self.rect.x(),
            "y": self.rect.y(),
            "width": self.rect.width(),
            "height": self.rect.height(),
        }
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EllipseShape":
        shape = super().from_dict(data)
        r = data["rect"]
        shape.rect = QRectF(r["x"], r["y"], r["width"], r["height"])
        return shape

    def flip_horizontal(self, center_x: float) -> None:
        wr = self.bounding_rect()
        new_x = 2 * center_x - wr.x() - wr.width()
        self.rect = QRectF(new_x, wr.y(), wr.width(), wr.height())
        self.transform.reset()

    def flip_vertical(self, center_y: float) -> None:
        wr = self.bounding_rect()
        new_y = 2 * center_y - wr.y() - wr.height()
        self.rect = QRectF(wr.x(), new_y, wr.width(), wr.height())
        self.transform.reset()


class LineShape(Shape):
    """直线图形"""

    def __init__(
        self,
        x1: float = 0,
        y1: float = 0,
        x2: float = 100,
        y2: float = 0,
        style: Optional[ShapeStyle] = None,
    ):
        super().__init__(ShapeType.LINE, style)
        self.line = QPointF(x1, y1), QPointF(x2, y2)

    def bounding_rect(self) -> QRectF:
        rect = QRectF(self.line[0], self.line[1]).normalized()
        if self.transform.isIdentity():
            return rect
        return self.transform.mapRect(rect)

    def _local_anchors(self) -> List[QPointF]:
        return [self.line[0], self.line[1]]

    def contains_point(self, point: QPointF) -> bool:
        if self.line[0] == self.line[1]:
            return False

        # 计算点到直线的距离
        dx = self.line[1].x() - self.line[0].x()
        dy = self.line[1].y() - self.line[0].y()

        if dx == 0:
            return abs(point.x() - self.line[0].x()) <= 5 and min(
                self.line[0].y(), self.line[1].y()
            ) <= point.y() <= max(self.line[0].y(), self.line[1].y())

        if dy == 0:
            return abs(point.y() - self.line[0].y()) <= 5 and min(
                self.line[0].x(), self.line[1].x()
            ) <= point.x() <= max(self.line[0].x(), self.line[1].x())

        # 一般情况：点到直线的距离
        t = (
            (point.x() - self.line[0].x()) * dx + (point.y() - self.line[0].y()) * dy
        ) / (dx * dx + dy * dy)
        t = max(0, min(1, t))

        closest_x = self.line[0].x() + t * dx
        closest_y = self.line[0].y() + t * dy

        distance = math.sqrt(
            (point.x() - closest_x) ** 2 + (point.y() - closest_y) ** 2
        )
        return distance <= 5

    def paint(self, painter: QPainter, pass_type: int = 0) -> None:
        if not self.visible:
            return

        # 直线只有边框，无填充
        if pass_type == 1:
            return

        painter.save()
        painter.setTransform(self.world_transform(), True)

        pen = self._style_pen()
        painter.setPen(pen)

        painter.drawLine(self.line[0], self.line[1])

        if self.selected:
            self._draw_selection_box(painter)

        painter.restore()

    def _draw_selection_box(self, painter: QPainter) -> None:
        """绘制选择框"""
        rect = QRectF(self.line[0], self.line[1]).normalized()
        rect.adjust(-5, -5, 5, 5)

        pen = QPen(QColor("#0078D4"))
        pen.setWidth(1)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect)

        # 绘制端点
        handle_size = 6
        for point in self.line:
            painter.drawRect(
                QRectF(
                    point.x() - handle_size / 2,
                    point.y() - handle_size / 2,
                    handle_size,
                    handle_size,
                )
            )

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data["line"] = {
            "x1": self.line[0].x(),
            "y1": self.line[0].y(),
            "x2": self.line[1].x(),
            "y2": self.line[1].y(),
        }
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LineShape":
        shape = super().from_dict(data)
        ln = data["line"]
        shape.line = (QPointF(ln["x1"], ln["y1"]), QPointF(ln["x2"], ln["y2"]))
        return shape

    def flip_horizontal(self, center_x: float) -> None:
        wp1 = self.transform.map(self.line[0])
        wp2 = self.transform.map(self.line[1])
        self.line = (QPointF(2 * center_x - wp1.x(), wp1.y()),
                      QPointF(2 * center_x - wp2.x(), wp2.y()))
        self.transform.reset()

    def flip_vertical(self, center_y: float) -> None:
        wp1 = self.transform.map(self.line[0])
        wp2 = self.transform.map(self.line[1])
        self.line = (QPointF(wp1.x(), 2 * center_y - wp1.y()),
                      QPointF(wp2.x(), 2 * center_y - wp2.y()))
        self.transform.reset()


class PolygonShape(Shape):
    """多边形图形"""

    def __init__(
        self, points: List[QPointF] = None, style: Optional[ShapeStyle] = None
    ):
        super().__init__(ShapeType.POLYGON, style)
        self.points = points or []

    def _local_anchors(self) -> List[QPointF]:
        return list(self.points) if self.points else []

    def bounding_rect(self) -> QRectF:
        if not self.points:
            return QRectF()
        min_x = min(p.x() for p in self.points)
        max_x = max(p.x() for p in self.points)
        min_y = min(p.y() for p in self.points)
        max_y = max(p.y() for p in self.points)
        rect = QRectF(min_x, min_y, max_x - min_x, max_y - min_y)
        if self.transform.isIdentity():
            return rect
        return self.transform.mapRect(rect)

    def contains_point(self, point: QPointF) -> bool:
        if not self.points or len(self.points) < 3:
            return False

        # 使用射线法判断点是否在多边形内
        x, y = point.x(), point.y()
        n = len(self.points)
        inside = False

        p1x, p1y = self.points[0].x(), self.points[0].y()
        for i in range(1, n + 1):
            p2x, p2y = self.points[i % n].x(), self.points[i % n].y()
            if y > min(p1y, p2y):
                if y <= max(p1y, p2y):
                    if x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or x <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y

        return inside

    def paint(self, painter: QPainter, pass_type: int = 0) -> None:
        if not self.visible or len(self.points) < 2:
            return

        painter.save()
        painter.setTransform(self.world_transform(), True)

        pen = self._style_pen()

        brush = QBrush(QColor(self.style.brush_color))
        brush.setStyle(self.style.brush_style)

        path = QPainterPath()
        path.moveTo(self.points[0])
        for point in self.points[1:]:
            path.lineTo(point)
        path.closeSubpath()

        if pass_type in (0, 1):
            painter.setPen(Qt.NoPen)
            painter.setBrush(brush)
            painter.setOpacity(self.style.opacity)
            painter.drawPath(path)

        if pass_type in (0, 2):
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.setOpacity(1.0)
            painter.drawPath(path)

        if self.selected and pass_type in (0, 2):
            self._draw_selection_box(painter)

        painter.restore()

    def _draw_selection_box(self, painter: QPainter) -> None:
        """绘制选择框"""
        if self.points:
            xs = [p.x() for p in self.points]; ys = [p.y() for p in self.points]
            rect = QRectF(min(xs), min(ys), max(xs)-min(xs), max(ys)-min(ys))
        else:
            rect = QRectF()
        rect.adjust(-5, -5, 5, 5)

        pen = QPen(QColor("#0078D4"))
        pen.setWidth(1)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect)

        # 绘制顶点
        handle_size = 6
        for point in self.points:
            painter.drawRect(
                QRectF(
                    point.x() - handle_size / 2,
                    point.y() - handle_size / 2,
                    handle_size,
                    handle_size,
                )
            )

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data["points"] = [{"x": p.x(), "y": p.y()} for p in self.points]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PolygonShape":
        shape = super().from_dict(data)
        shape.points = [QPointF(p["x"], p["y"]) for p in data.get("points", [])]
        return shape

    def flip_horizontal(self, center_x: float) -> None:
        wp = [self.transform.map(p) for p in self.points]
        self.points = [QPointF(2 * center_x - p.x(), p.y()) for p in wp]
        self.transform.reset()

    def flip_vertical(self, center_y: float) -> None:
        wp = [self.transform.map(p) for p in self.points]
        self.points = [QPointF(p.x(), 2 * center_y - p.y()) for p in wp]
        self.transform.reset()


class PolylineShape(Shape):
    """折线图形"""

    def __init__(
        self, points: List[QPointF] = None, style: Optional[ShapeStyle] = None
    ):
        super().__init__(ShapeType.POLYLINE, style)
        self.points = points or []

    def _local_anchors(self) -> List[QPointF]:
        return list(self.points) if self.points else []

    def bounding_rect(self) -> QRectF:
        if not self.points:
            return QRectF()
        min_x = min(p.x() for p in self.points)
        max_x = max(p.x() for p in self.points)
        min_y = min(p.y() for p in self.points)
        max_y = max(p.y() for p in self.points)
        rect = QRectF(min_x, min_y, max_x - min_x, max_y - min_y)
        if self.transform.isIdentity():
            return rect
        return self.transform.mapRect(rect)

    def contains_point(self, point: QPointF) -> bool:
        if not self.points or len(self.points) < 2:
            return False

        # 检查点是否在折线的任意线段附近
        tolerance = 5

        for i in range(len(self.points) - 1):
            p1 = self.points[i]
            p2 = self.points[i + 1]

            # 计算点到线段的距离
            dx = p2.x() - p1.x()
            dy = p2.y() - p1.y()

            if dx == 0 and dy == 0:
                continue

            if dx == 0:
                if abs(point.x() - p1.x()) <= tolerance and min(
                    p1.y(), p2.y()
                ) <= point.y() <= max(p1.y(), p2.y()):
                    return True
            elif dy == 0:
                if abs(point.y() - p1.y()) <= tolerance and min(
                    p1.x(), p2.x()
                ) <= point.x() <= max(p1.x(), p2.x()):
                    return True
            else:
                t = ((point.x() - p1.x()) * dx + (point.y() - p1.y()) * dy) / (
                    dx * dx + dy * dy
                )
                t = max(0, min(1, t))

                closest_x = p1.x() + t * dx
                closest_y = p1.y() + t * dy

                distance = math.sqrt(
                    (point.x() - closest_x) ** 2 + (point.y() - closest_y) ** 2
                )
                if distance <= tolerance:
                    return True

        return False

    def paint(self, painter: QPainter, pass_type: int = 0) -> None:
        if not self.visible or len(self.points) < 2:
            return

        # 折线是开放路径，不填充
        if pass_type == 1:
            return

        painter.save()
        painter.setTransform(self.world_transform(), True)

        pen = self._style_pen()

        path = QPainterPath()
        path.moveTo(self.points[0])
        for point in self.points[1:]:
            path.lineTo(point)

        if pass_type in (0, 2):
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.setOpacity(1.0)
            painter.drawPath(path)

        if self.selected:
            self._draw_selection_box(painter)

        painter.restore()

    def _draw_selection_box(self, painter: QPainter) -> None:
        """绘制选择框"""
        if self.points:
            xs = [p.x() for p in self.points]; ys = [p.y() for p in self.points]
            rect = QRectF(min(xs), min(ys), max(xs)-min(xs), max(ys)-min(ys))
        else:
            rect = QRectF()
        rect.adjust(-5, -5, 5, 5)

        pen = QPen(QColor("#0078D4"))
        pen.setWidth(1)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect)

        # 绘制顶点
        handle_size = 6
        for point in self.points:
            painter.drawRect(
                QRectF(
                    point.x() - handle_size / 2,
                    point.y() - handle_size / 2,
                    handle_size,
                    handle_size,
                )
            )

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data["points"] = [{"x": p.x(), "y": p.y()} for p in self.points]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PolylineShape":
        shape = super().from_dict(data)
        shape.points = [QPointF(p["x"], p["y"]) for p in data.get("points", [])]
        return shape


class DiamondShape(Shape):
    """菱形（流程图决策符号）"""

    def __init__(self, x=0, y=0, width=120, height=80, style=None):
        super().__init__(ShapeType.DIAMOND, style)
        self.rect = QRectF(x, y, width, height)

    def _vertices(self):
        r = self.rect
        return [
            QPointF(r.x() + r.width() / 2, r.y()),
            QPointF(r.x() + r.width(), r.y() + r.height() / 2),
            QPointF(r.x() + r.width() / 2, r.y() + r.height()),
            QPointF(r.x(), r.y() + r.height() / 2),
        ]

    def _local_anchors(self):
        v = self._vertices()
        edges = [
            QPointF((v[0].x() + v[1].x()) / 2, (v[0].y() + v[1].y()) / 2),
            QPointF((v[1].x() + v[2].x()) / 2, (v[1].y() + v[2].y()) / 2),
            QPointF((v[2].x() + v[3].x()) / 2, (v[2].y() + v[3].y()) / 2),
            QPointF((v[3].x() + v[0].x()) / 2, (v[3].y() + v[0].y()) / 2),
        ]
        return v + edges

    def bounding_rect(self) -> QRectF:
        if self.transform.isIdentity():
            return self.rect
        return self.transform.mapRect(self.rect)

    def contains_point(self, point: QPointF) -> bool:
        verts = self._vertices()
        n = len(verts)
        inside = False
        j = n - 1
        for i in range(n):
            if ((verts[i].y() > point.y()) != (verts[j].y() > point.y())) and \
               (point.x() < (verts[j].x() - verts[i].x()) * (point.y() - verts[i].y()) / (verts[j].y() - verts[i].y()) + verts[i].x()):
                inside = not inside
            j = i
        return inside

    def paint(self, painter: QPainter, pass_type: int = 0) -> None:
        if not self.visible:
            return
        painter.save()
        painter.setTransform(self.world_transform(), True)
        pen = self._style_pen()
        brush = QBrush(QColor(self.style.brush_color))
        brush.setStyle(self.style.brush_style)
        verts = self._vertices()
        path = QPainterPath()
        path.moveTo(verts[0])
        for v in verts[1:]:
            path.lineTo(v)
        path.closeSubpath()
        if pass_type in (0, 1):
            painter.setPen(Qt.NoPen)
            painter.setBrush(brush)
            painter.setOpacity(self.style.opacity)
            painter.drawPath(path)
        if pass_type in (0, 2):
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.setOpacity(1.0)
            painter.drawPath(path)
        if self.selected and pass_type in (0, 2):
            self._draw_selection_box(painter)
        painter.restore()

    def _draw_selection_box(self, painter: QPainter) -> None:
        r = self.rect
        pen = QPen(QColor("#0078D4"))
        pen.setWidth(1)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(r)
        handle_size = 6
        for h in [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]:
            painter.drawRect(QRectF(h.x() - handle_size / 2, h.y() - handle_size / 2, handle_size, handle_size))

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data["rect"] = {"x": self.rect.x(), "y": self.rect.y(), "width": self.rect.width(), "height": self.rect.height()}
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiamondShape":
        shape = super().from_dict(data)
        r = data["rect"]
        shape.rect = QRectF(r["x"], r["y"], r["width"], r["height"])
        return shape

    def flip_horizontal(self, center_x: float) -> None:
        wr = self.bounding_rect()
        new_x = 2 * center_x - wr.x() - wr.width()
        self.rect = QRectF(new_x, wr.y(), wr.width(), wr.height())
        self.transform.reset()

    def flip_vertical(self, center_y: float) -> None:
        wr = self.bounding_rect()
        new_y = 2 * center_y - wr.y() - wr.height()
        self.rect = QRectF(wr.x(), new_y, wr.width(), wr.height())
        self.transform.reset()


class RoundedRectShape(Shape):
    """圆角矩形（流程图开始/结束符号）"""

    def __init__(self, x=0, y=0, width=120, height=60, radius=20, style=None):
        super().__init__(ShapeType.ROUNDED_RECT, style)
        self.rect = QRectF(x, y, width, height)
        self.radius = radius

    def bounding_rect(self) -> QRectF:
        if self.transform.isIdentity():
            return self.rect
        return self.transform.mapRect(self.rect)

    def contains_point(self, point: QPointF) -> bool:
        return self.rect.contains(point)

    def paint(self, painter: QPainter, pass_type: int = 0) -> None:
        if not self.visible:
            return
        painter.save()
        painter.setTransform(self.world_transform(), True)
        pen = self._style_pen()
        brush = QBrush(QColor(self.style.brush_color))
        brush.setStyle(self.style.brush_style)
        if pass_type in (0, 1):
            painter.setPen(Qt.NoPen)
            painter.setBrush(brush)
            painter.setOpacity(self.style.opacity)
            painter.drawRoundedRect(self.rect, self.radius, self.radius)
        if pass_type in (0, 2):
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.setOpacity(1.0)
            painter.drawRoundedRect(self.rect, self.radius, self.radius)
        if self.selected and pass_type in (0, 2):
            self._draw_selection_box(painter)
        painter.restore()

    def _draw_selection_box(self, painter: QPainter) -> None:
        r = self.rect
        pen = QPen(QColor("#0078D4"))
        pen.setWidth(1)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(r)
        handle_size = 6
        for h in [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]:
            painter.drawRect(QRectF(h.x() - handle_size / 2, h.y() - handle_size / 2, handle_size, handle_size))

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data["rect"] = {"x": self.rect.x(), "y": self.rect.y(), "width": self.rect.width(), "height": self.rect.height()}
        data["radius"] = self.radius
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RoundedRectShape":
        shape = super().from_dict(data)
        r = data["rect"]
        shape.rect = QRectF(r["x"], r["y"], r["width"], r["height"])
        shape.radius = data.get("radius", 20)
        return shape

    def flip_horizontal(self, center_x: float) -> None:
        wr = self.bounding_rect()
        new_x = 2 * center_x - wr.x() - wr.width()
        self.rect = QRectF(new_x, wr.y(), wr.width(), wr.height())
        self.transform.reset()

    def flip_vertical(self, center_y: float) -> None:
        wr = self.bounding_rect()
        new_y = 2 * center_y - wr.y() - wr.height()
        self.rect = QRectF(wr.x(), new_y, wr.width(), wr.height())
        self.transform.reset()


class ParallelogramShape(Shape):
    """平行四边形（流程图输入/输出符号）"""

    def __init__(self, x=0, y=0, width=120, height=60, skew=0.2, style=None):
        super().__init__(ShapeType.PARALLELOGRAM, style)
        self.rect = QRectF(x, y, width, height)
        self.skew = skew

    def _vertices(self):
        r = self.rect
        s = r.width() * self.skew
        return [
            QPointF(r.x() + s, r.y()),
            QPointF(r.x() + r.width(), r.y()),
            QPointF(r.x() + r.width() - s, r.y() + r.height()),
            QPointF(r.x(), r.y() + r.height()),
        ]

    def _local_anchors(self):
        v = self._vertices()
        edge_mids = [
            QPointF((v[0].x() + v[1].x()) / 2, (v[0].y() + v[1].y()) / 2),
            QPointF((v[1].x() + v[2].x()) / 2, (v[1].y() + v[2].y()) / 2),
            QPointF((v[2].x() + v[3].x()) / 2, (v[2].y() + v[3].y()) / 2),
            QPointF((v[3].x() + v[0].x()) / 2, (v[3].y() + v[0].y()) / 2),
        ]
        return edge_mids + v

    def bounding_rect(self) -> QRectF:
        if self.transform.isIdentity():
            return self.rect
        return self.transform.mapRect(self.rect)

    def contains_point(self, point: QPointF) -> bool:
        verts = self._vertices()
        n = len(verts)
        inside = False
        j = n - 1
        for i in range(n):
            if ((verts[i].y() > point.y()) != (verts[j].y() > point.y())) and \
               (point.x() < (verts[j].x() - verts[i].x()) * (point.y() - verts[i].y()) / (verts[j].y() - verts[i].y()) + verts[i].x()):
                inside = not inside
            j = i
        return inside

    def paint(self, painter: QPainter, pass_type: int = 0) -> None:
        if not self.visible:
            return
        painter.save()
        painter.setTransform(self.world_transform(), True)
        pen = self._style_pen()
        brush = QBrush(QColor(self.style.brush_color))
        brush.setStyle(self.style.brush_style)
        verts = self._vertices()
        path = QPainterPath()
        path.moveTo(verts[0])
        for v in verts[1:]:
            path.lineTo(v)
        path.closeSubpath()
        if pass_type in (0, 1):
            painter.setPen(Qt.NoPen)
            painter.setBrush(brush)
            painter.setOpacity(self.style.opacity)
            painter.drawPath(path)
        if pass_type in (0, 2):
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.setOpacity(1.0)
            painter.drawPath(path)
        if self.selected and pass_type in (0, 2):
            self._draw_selection_box(painter)
        painter.restore()

    def _draw_selection_box(self, painter: QPainter) -> None:
        r = self.rect
        pen = QPen(QColor("#0078D4"))
        pen.setWidth(1)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(r)
        handle_size = 6
        for h in [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]:
            painter.drawRect(QRectF(h.x() - handle_size / 2, h.y() - handle_size / 2, handle_size, handle_size))

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data["rect"] = {"x": self.rect.x(), "y": self.rect.y(), "width": self.rect.width(), "height": self.rect.height()}
        data["skew"] = self.skew
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ParallelogramShape":
        shape = super().from_dict(data)
        r = data["rect"]
        shape.rect = QRectF(r["x"], r["y"], r["width"], r["height"])
        shape.skew = data.get("skew", 0.2)
        return shape

    def flip_horizontal(self, center_x: float) -> None:
        wr = self.bounding_rect()
        new_x = 2 * center_x - wr.x() - wr.width()
        self.rect = QRectF(new_x, wr.y(), wr.width(), wr.height())
        self.transform.reset()

    def flip_vertical(self, center_y: float) -> None:
        wr = self.bounding_rect()
        new_y = 2 * center_y - wr.y() - wr.height()
        self.rect = QRectF(wr.x(), new_y, wr.width(), wr.height())
        self.transform.reset()

    def flip_horizontal(self, center_x: float) -> None:
        wp = [self.transform.map(p) for p in self.points]
        self.points = [QPointF(2 * center_x - p.x(), p.y()) for p in wp]
        self.transform.reset()

    def flip_vertical(self, center_y: float) -> None:
        wp = [self.transform.map(p) for p in self.points]
        self.points = [QPointF(p.x(), 2 * center_y - p.y()) for p in wp]
        self.transform.reset()


# ──────────────────────────────────────────────
#  电路图 + 组织结构图符号库
# ──────────────────────────────────────────────

class _SymbolShape(Shape):
    """电路符号基类：填充 pass 跳过，只画线条"""

    def __init__(self, shape_type, x=0, y=0, width=80, height=40, style=None):
        super().__init__(shape_type, style)
        self.rect = QRectF(x, y, width, height)

    def bounding_rect(self):
        if self.transform.isIdentity():
            return self.rect
        return self.transform.mapRect(self.rect)

    def contains_point(self, point):
        return self.rect.contains(point)

    def paint(self, painter, pass_type=0):
        if not self.visible:
            return
        if pass_type == 1:
            return
        painter.save()
        painter.setTransform(self.world_transform(), True)
        pen = self._style_pen()
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.setOpacity(1.0)
        self._draw_symbol(painter)
        if self.selected and pass_type in (0, 2):
            r = self.rect
            p = QPen(QColor("#0078D4"))
            p.setWidth(1)
            p.setStyle(Qt.DashLine)
            painter.setPen(p)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(r)
        painter.restore()

    def _draw_symbol(self, painter):
        pass

    def to_dict(self):
        data = super().to_dict()
        data["rect"] = {"x": self.rect.x(), "y": self.rect.y(),
                         "width": self.rect.width(), "height": self.rect.height()}
        return data

    @staticmethod
    def _rect_from_data(data):
        r = data["rect"]
        return QRectF(r["x"], r["y"], r["width"], r["height"])

    def flip_horizontal(self, center_x):
        wr = self.bounding_rect()
        self.rect = QRectF(2 * center_x - wr.x() - wr.width(), wr.y(), wr.width(), wr.height())
        self.transform.reset()

    def flip_vertical(self, center_y):
        wr = self.bounding_rect()
        self.rect = QRectF(wr.x(), 2 * center_y - wr.y() - wr.height(), wr.width(), wr.height())
        self.transform.reset()


class ResistorShape(_SymbolShape):
    def __init__(self, x=0, y=0, width=120, height=40, style=None):
        super().__init__(ShapeType.RESISTOR, x, y, width, height, style)

    def _draw_symbol(self, painter):
        r = self.rect
        pts = max(int(r.width() / 10), 2)
        sw = r.width() / pts
        path = QPainterPath()
        path.moveTo(r.left(), r.center().y())
        for i in range(1, pts):
            px = r.left() + i * sw
            py = r.center().y() + (r.height() / 3 if i % 2 == 1 else -r.height() / 3)
            path.lineTo(px, py)
        path.lineTo(r.right(), r.center().y())
        painter.drawPath(path)

    @classmethod
    def from_dict(cls, data):
        shape = super().from_dict(data)
        shape.rect = cls._rect_from_data(data)
        return shape


class CapacitorShape(_SymbolShape):
    def __init__(self, x=0, y=0, width=60, height=40, style=None):
        super().__init__(ShapeType.CAPACITOR, x, y, width, height, style)

    def _draw_symbol(self, painter):
        r = self.rect
        cx = r.center().x()
        g = r.width() * 0.15
        painter.drawLine(QPointF(r.left(), r.center().y()), QPointF(cx - g, r.center().y()))
        painter.drawLine(QPointF(cx - g, r.top()), QPointF(cx - g, r.bottom()))
        painter.drawLine(QPointF(cx + g, r.top()), QPointF(cx + g, r.bottom()))
        painter.drawLine(QPointF(cx + g, r.center().y()), QPointF(r.right(), r.center().y()))

    @classmethod
    def from_dict(cls, data):
        shape = super().from_dict(data)
        shape.rect = cls._rect_from_data(data)
        return shape


class InductorShape(_SymbolShape):
    def __init__(self, x=0, y=0, width=100, height=40, style=None):
        super().__init__(ShapeType.INDUCTOR, x, y, width, height, style)

    def _draw_symbol(self, painter):
        r = self.rect
        loops = 4
        lw = r.width() / (loops * 2 + 2)
        path = QPainterPath()
        sx = r.left() + lw
        path.moveTo(r.left(), r.center().y())
        path.lineTo(sx, r.center().y())
        for i in range(loops):
            cx = sx + lw * (2 * i + 1)
            path.arcTo(QRectF(cx - lw, r.top(), lw * 2, r.height()), 0, 180)
        path.lineTo(r.right(), r.center().y())
        painter.drawPath(path)

    @classmethod
    def from_dict(cls, data):
        shape = super().from_dict(data)
        shape.rect = cls._rect_from_data(data)
        return shape


class GroundShape(_SymbolShape):
    def __init__(self, x=0, y=0, width=60, height=40, style=None):
        super().__init__(ShapeType.GROUND, x, y, width, height, style)

    def _draw_symbol(self, painter):
        r = self.rect
        cx = r.center().x()
        ty = r.top() + r.height() * 0.15
        painter.drawLine(QPointF(cx, r.top()), QPointF(cx, ty))
        for i, sc in enumerate([1.0, 0.6, 0.3]):
            y = ty + (r.height() - ty) * (i + 1) / 4
            hw = r.width() * sc / 2
            painter.drawLine(QPointF(cx - hw, y), QPointF(cx + hw, y))

    @classmethod
    def from_dict(cls, data):
        shape = super().from_dict(data)
        shape.rect = cls._rect_from_data(data)
        return shape


class BatteryShape(_SymbolShape):
    def __init__(self, x=0, y=0, width=60, height=40, style=None):
        super().__init__(ShapeType.BATTERY, x, y, width, height, style)

    def _draw_symbol(self, painter):
        r = self.rect
        cx = r.center().x()
        g = r.width() * 0.12
        painter.drawLine(QPointF(r.left(), r.center().y()), QPointF(cx - g * 3, r.center().y()))
        painter.drawLine(QPointF(cx - g * 3, r.top() + 2), QPointF(cx - g * 3, r.bottom() - 2))
        painter.drawLine(QPointF(cx - g, r.top() + 4), QPointF(cx - g, r.bottom() - 4))
        painter.drawLine(QPointF(cx + g, r.top() + 4), QPointF(cx + g, r.bottom() - 4))
        painter.drawLine(QPointF(cx + g * 3, r.top() + 2), QPointF(cx + g * 3, r.bottom() - 2))
        painter.drawLine(QPointF(cx + g * 3, r.center().y()), QPointF(r.right(), r.center().y()))

    @classmethod
    def from_dict(cls, data):
        shape = super().from_dict(data)
        shape.rect = cls._rect_from_data(data)
        return shape


class DiodeShape(_SymbolShape):
    def __init__(self, x=0, y=0, width=80, height=40, style=None):
        super().__init__(ShapeType.DIODE, x, y, width, height, style)

    def _draw_symbol(self, painter):
        r = self.rect
        cx = r.center().x()
        cy = r.center().y()
        tw = r.height() * 0.6
        ts = cx - tw / 2
        painter.drawLine(QPointF(r.left(), cy), QPointF(ts, cy))
        path = QPainterPath()
        path.moveTo(ts, r.top())
        path.lineTo(ts, r.bottom())
        path.lineTo(ts + tw, cy)
        path.closeSubpath()
        painter.drawPath(path)
        lx = ts + tw + 2
        painter.drawLine(QPointF(lx, r.top()), QPointF(lx, r.bottom()))
        painter.drawLine(QPointF(lx, cy), QPointF(r.right(), cy))

    @classmethod
    def from_dict(cls, data):
        shape = super().from_dict(data)
        shape.rect = cls._rect_from_data(data)
        return shape


class OrgNodeShape(_SymbolShape):
    def __init__(self, x=0, y=0, width=120, height=50, style=None):
        super().__init__(ShapeType.ORG_NODE, x, y, width, height, style)

    def paint(self, painter, pass_type=0):
        if not self.visible:
            return
        painter.save()
        painter.setTransform(self.world_transform(), True)
        pen = self._style_pen()
        brush = QBrush(QColor(self.style.brush_color))
        brush.setStyle(self.style.brush_style)
        if pass_type in (0, 1):
            painter.setPen(Qt.NoPen)
            painter.setBrush(brush)
            painter.setOpacity(self.style.opacity)
            painter.drawRoundedRect(self.rect, 8, 8)
        if pass_type in (0, 2):
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.setOpacity(1.0)
            painter.drawRoundedRect(self.rect, 8, 8)
        if self.selected and pass_type in (0, 2):
            r = self.rect
            p = QPen(QColor("#0078D4"))
            p.setWidth(1)
            p.setStyle(Qt.DashLine)
            painter.setPen(p)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(r)
        painter.restore()

    @classmethod
    def from_dict(cls, data):
        shape = super().from_dict(data)
        shape.rect = cls._rect_from_data(data)
        return shape


class TextShape(Shape):
    """文字图形"""

    def __init__(self, x=0, y=0, text="文字", font_size=16, style=None):
        super().__init__(ShapeType.TEXT, style)
        self.text = text
        self.font_size = font_size
        self.rect = self._calc_rect(x, y)

    def _calc_rect(self, x, y):
        from PyQt5.QtGui import QFontMetrics
        f = QFont(); f.setPointSize(self.font_size)
        m = QFontMetrics(f)
        w = max(40, m.horizontalAdvance(self.text) + 10)
        h = m.height() + 8
        return QRectF(x, y, w, h)

    def set_text(self, text):
        self.text = text
        self.rect = self._calc_rect(self.rect.x(), self.rect.y())

    def bounding_rect(self) -> QRectF:
        if self.transform.isIdentity():
            return self.rect
        return self.transform.mapRect(self.rect)

    def contains_point(self, point: QPointF) -> bool:
        return self.rect.contains(point)

    def paint(self, painter: QPainter, pass_type: int = 0) -> None:
        if not self.visible or pass_type == 1:
            return
        painter.save()
        painter.setTransform(self.world_transform(), True)
        font = painter.font()
        font.setPointSize(self.font_size)
        painter.setFont(font)
        pen = QPen(QColor(self.style.pen_color))
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.setOpacity(1.0)
        painter.drawText(self.rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, self.text)
        if self.selected:
            r = self.rect
            dp = QPen(QColor("#0078D4"))
            dp.setWidth(1); dp.setStyle(Qt.DashLine)
            painter.setPen(dp); painter.drawRect(r)
        painter.restore()

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data["rect"] = {"x": self.rect.x(), "y": self.rect.y(),
                         "width": self.rect.width(), "height": self.rect.height()}
        data["text"] = self.text
        data["font_size"] = self.font_size
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TextShape":
        shape = super().from_dict(data)
        r = data.get("rect", {})
        shape.rect = QRectF(r.get("x", 0), r.get("y", 0), r.get("width", 200), r.get("height", 40))
        shape.text = data.get("text", "文字")
        shape.font_size = data.get("font_size", 16)
        return shape

    def flip_horizontal(self, center_x): pass
    def flip_vertical(self, center_y): pass


class ConnectionShape(Shape):
    """连接线——连接两个图形的锚点，源图形移动时自动跟随"""

    def __init__(self, source_shape=None, source_anchor=0,
                 target_shape=None, target_anchor=2, style=None):
        super().__init__(ShapeType.CONNECTION, style)
        self.source_shape = source_shape
        self.source_anchor = source_anchor
        self.target_shape = target_shape
        self.target_anchor = target_anchor
        self._cached_p1 = QPointF()
        self._cached_p2 = QPointF()
        self.routed_points = []
        self._update_endpoints()

    def _update_endpoints(self):
        if self.source_shape:
            pts = self.source_shape.get_anchor_points()
            if self.source_anchor < len(pts):
                self._cached_p1 = pts[self.source_anchor]
        if self.target_shape:
            pts = self.target_shape.get_anchor_points()
            if self.target_anchor < len(pts):
                self._cached_p2 = pts[self.target_anchor]

    def refresh(self):
        self._update_endpoints()

    def bounding_rect(self) -> QRectF:
        self._update_endpoints()
        points = self.routed_points or [self._cached_p1, self._cached_p2]
        rect = QRectF(points[0], points[0])
        for point in points[1:]: rect = rect.united(QRectF(point, point))
        return rect.normalized().adjusted(-5, -5, 5, 5)

    def contains_point(self, point: QPointF) -> bool:
        self._update_endpoints()
        p1, p2 = self._cached_p1, self._cached_p2
        if p1 == p2:
            return (point - p1).manhattanLength() < 5
        line = QLineF(p1, p2)
        d = abs((p2.x() - p1.x()) * (p1.y() - point.y()) -
                (p1.x() - point.x()) * (p2.y() - p1.y())) / line.length()
        v1 = point - p1; v2 = p2 - p1
        t = (v1.x() * v2.x() + v1.y() * v2.y()) / (line.length() ** 2)
        return 0 <= t <= 1 and d <= 8

    def paint(self, painter: QPainter, pass_type: int = 0) -> None:
        if not self.visible or pass_type == 1:
            return
        self._update_endpoints()
        p1, p2 = self._cached_p1, self._cached_p2
        painter.save()
        pen = self._style_pen()
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.setOpacity(1.0)
        points = self.routed_points or [p1, p2]
        for first, second in zip(points, points[1:]):
            painter.drawLine(first, second)
        if p1 != p2:
            angle = math.atan2(p2.y() - p1.y(), p2.x() - p1.x())
            alen = 12; aa = math.radians(25)
            tip = p2
            ax1 = QPointF(tip.x() - alen * math.cos(angle - aa),
                           tip.y() - alen * math.sin(angle - aa))
            ax2 = QPointF(tip.x() - alen * math.cos(angle + aa),
                           tip.y() - alen * math.sin(angle + aa))
            path = QPainterPath(); path.moveTo(tip); path.lineTo(ax1); path.lineTo(ax2); path.closeSubpath()
            painter.setBrush(QBrush(QColor(self.style.pen_color)))
            painter.drawPath(path)
        if self.selected:
            r = QRectF(self._cached_p1, self._cached_p2).normalized().adjusted(-5,-5,5,5)
            dp = QPen(QColor("#0078D4")); dp.setWidth(1); dp.setStyle(Qt.DashLine)
            painter.setPen(dp); painter.drawRect(r)
        painter.restore()

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data["source_anchor"] = self.source_anchor
        data["target_anchor"] = self.target_anchor
        data["source_index"] = getattr(self, '_source_index', -1)
        data["target_index"] = getattr(self, '_target_index', -1)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConnectionShape":
        shape = super().from_dict(data)
        shape.source_anchor = data.get("source_anchor", 0)
        shape.target_anchor = data.get("target_anchor", 2)
        shape._source_index = data.get("source_index", -1)
        shape._target_index = data.get("target_index", -1)
        return shape
