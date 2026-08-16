"""几何变换模块"""

from PyQt5.QtCore import QPointF
from PyQt5.QtGui import QTransform, QPolygonF
import math


class TransformUtils:
    """几何变换工具类"""

    @staticmethod
    def distance(p1: QPointF, p2: QPointF) -> float:
        """计算两点之间的距离"""
        return math.sqrt((p2.x() - p1.x()) ** 2 + (p2.y() - p1.y()) ** 2)

    @staticmethod
    def angle(p1: QPointF, p2: QPointF) -> float:
        """计算两点之间的角度（弧度）"""
        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        return math.atan2(dy, dx)

    @staticmethod
    def rotate_point(point: QPointF, angle: float, center: QPointF) -> QPointF:
        """绕指定点旋转点"""
        # 平移到原点
        translated = QPointF(point.x() - center.x(), point.y() - center.y())

        # 旋转
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        rotated_x = translated.x() * cos_a - translated.y() * sin_a
        rotated_y = translated.x() * sin_a + translated.y() * cos_a

        # 平移回去
        return QPointF(rotated_x + center.x(), rotated_y + center.y())

    @staticmethod
    def scale_point(point: QPointF, sx: float, sy: float, center: QPointF) -> QPointF:
        """绕指定点缩放点"""
        # 平移到原点
        translated = QPointF(point.x() - center.x(), point.y() - center.y())

        # 缩放
        scaled = QPointF(translated.x() * sx, translated.y() * sy)

        # 平移回去
        return QPointF(scaled.x() + center.x(), scaled.y() + center.y())

    @staticmethod
    def bounding_rect_with_transform(rect, transform: QTransform) -> QPointF:
        """获取应用变换后的边界矩形"""
        # 矩形的四个角
        corners = [
            QPointF(rect.topLeft()),
            QPointF(rect.topRight()),
            QPointF(rect.bottomRight()),
            QPointF(rect.bottomLeft()),
        ]

        # 应用变换
        transformed_corners = [transform.map(corner) for corner in corners]

        # 计算新的边界矩形
        min_x = min(corner.x() for corner in transformed_corners)
        max_x = max(corner.x() for corner in transformed_corners)
        min_y = min(corner.y() for corner in transformed_corners)
        max_y = max(corner.y() for corner in transformed_corners)

        return QPointF(max_x - min_x, max_y - min_y)

    @staticmethod
    def line_intersection(
        p1: QPointF, p2: QPointF, p3: QPointF, p4: QPointF
    ) -> QPointF:
        """计算两条线段的交点"""
        x1, y1 = p1.x(), p1.y()
        x2, y2 = p2.x(), p2.y()
        x3, y3 = p3.x(), p3.y()
        x4, y4 = p4.x(), p4.y()

        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(denom) < 1e-10:
            # 平行线
            return None

        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom

        if 0 <= t <= 1 and 0 <= u <= 1:
            x = x1 + t * (x2 - x1)
            y = y1 + t * (y2 - y1)
            return QPointF(x, y)

        return None

    @staticmethod
    def snap_to_grid(point: QPointF, grid_size: float) -> QPointF:
        """吸附到网格"""
        snapped_x = round(point.x() / grid_size) * grid_size
        snapped_y = round(point.y() / grid_size) * grid_size
        return QPointF(snapped_x, snapped_y)

    @staticmethod
    def rect_from_points(points: list) -> QPointF:
        """从点列表创建矩形"""
        if not points:
            return QPointF(0, 0)

        min_x = min(p.x() for p in points)
        max_x = max(p.x() for p in points)
        min_y = min(p.y() for p in points)
        max_y = max(p.y() for p in points)

        return QPointF(max_x - min_x, max_y - min_y)


class Transform:
    """几何变换类"""

    def __init__(self):
        self.transform = QTransform()

    def translate(self, dx: float, dy: float) -> "Transform":
        """平移变换"""
        self.transform.translate(dx, dy)
        return self

    def rotate(self, angle: float, center: QPointF = None) -> "Transform":
        """旋转变换"""
        if center:
            self.transform.translate(-center.x(), -center.y())
            self.transform.rotate(angle)
            self.transform.translate(center.x(), center.y())
        else:
            self.transform.rotate(angle)
        return self

    def scale(self, sx: float, sy: float, center: QPointF = None) -> "Transform":
        """缩放变换"""
        if center:
            self.transform.translate(center.x(), center.y())
            self.transform.scale(sx, sy)
            self.transform.translate(-center.x(), -center.y())
        else:
            self.transform.scale(sx, sy)
        return self

    def shear(self, sh: float, sv: float) -> "Transform":
        """剪切变换"""
        self.transform.shear(sh, sv)
        return self

    def flip_horizontal(self, center_x: float) -> "Transform":
        """水平翻转"""
        self.transform.translate(-center_x, 0)
        self.transform.scale(-1, 1)
        self.transform.translate(center_x, 0)
        return self

    def flip_vertical(self, center_y: float) -> "Transform":
        """垂直翻转"""
        self.transform.translate(0, -center_y)
        self.transform.scale(1, -1)
        self.transform.translate(0, center_y)
        return self

    def get_transform(self) -> QTransform:
        """获取变换矩阵"""
        return self.transform

    def set_transform(self, transform: QTransform) -> "Transform":
        """设置变换矩阵"""
        self.transform = transform
        return self

    def reset(self) -> "Transform":
        """重置变换"""
        self.transform.reset()
        return self

    def combine(self, other: "Transform") -> "Transform":
        """组合变换"""
        self.transform *= other.transform
        return self

    def apply_to_point(self, point: QPointF) -> QPointF:
        """应用变换到点"""
        return self.transform.map(point)

    def apply_to_rect(self, rect) -> QPointF:
        """应用变换到矩形"""
        return TransformUtils.bounding_rect_with_transform(rect, self.transform)
