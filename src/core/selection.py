"""选择管理模块"""

from PyQt5.QtCore import QRectF, QPointF, Qt
from PyQt5.QtGui import QPen, QColor, QPainter, QBrush
from typing import List, Set, Optional, Tuple

from .shape import Shape


class SelectionMode:
    """选择模式"""

    SINGLE = 0  # 单选
    MULTI = 1  # 多选
    BOX = 2  # 框选


class SelectionManager:
    """选择管理器"""

    def __init__(self):
        self.shapes: Set[Shape] = set()
        self.selection_mode = SelectionMode.SINGLE
        self.selection_box: Optional[QRectF] = None
        self.is_selecting = False
        self.start_point: Optional[QPointF] = None
        self.end_point: Optional[QPointF] = None
        self.last_selection_box: Optional[QRectF] = None

    def set_selection_mode(self, mode: SelectionMode) -> None:
        """设置选择模式"""
        self.selection_mode = mode
        if mode == SelectionMode.SINGLE:
            self.clear_selection()

    def add_shape(self, shape: Shape) -> None:
        """添加图形到选择"""
        shape.selected = True
        self.shapes.add(shape)

    def remove_shape(self, shape: Shape) -> None:
        """从选择中移除图形"""
        shape.selected = False
        self.shapes.discard(shape)

    def toggle_shape(self, shape: Shape) -> None:
        """切换图形的选择状态"""
        if shape.selected:
            self.remove_shape(shape)
        else:
            if self.selection_mode == SelectionMode.SINGLE:
                self.clear_selection()
            self.add_shape(shape)

    def clear_selection(self) -> None:
        """清除所有选择"""
        for shape in self.shapes:
            shape.selected = False
        self.shapes.clear()
        self.selection_box = None

    def get_selected_shapes(self) -> List[Shape]:
        """获取选中的图形列表"""
        return list(self.shapes)

    def get_bounding_rect(self) -> QRectF:
        """获取选中图形的边界矩形"""
        if not self.shapes:
            return QRectF()

        first_shape = next(iter(self.shapes))
        rect = first_shape.bounding_rect()

        for shape in self.shapes:
            shape_rect = shape.bounding_rect()
            rect = rect.united(shape_rect)

        return rect

    def start_box_selection(self, point: QPointF) -> None:
        """开始框选"""
        self.is_selecting = True
        self.start_point = point
        self.end_point = point
        self.last_selection_box = None

    def update_box_selection(self, point: QPointF) -> None:
        """更新框选"""
        if not self.is_selecting:
            return

        self.end_point = point
        self.last_selection_box = self.get_selection_box()

    def end_box_selection(self) -> None:
        """结束框选"""
        if not self.is_selecting:
            return

        self.is_selecting = False
        selection_box = self.get_selection_box()

        if self.selection_mode == SelectionMode.BOX:
            # 框选模式：选择框内的所有图形
            self.clear_selection()
            # 这里需要传入所有图形列表，由外部调用者提供
            self._select_shapes_in_box(selection_box)

        self.selection_box = selection_box
        self.start_point = None
        self.end_point = None

    def get_selection_box(self) -> QRectF:
        """获取选择框"""
        if not self.start_point or not self.end_point:
            return QRectF()

        x1, y1 = self.start_point.x(), self.start_point.y()
        x2, y2 = self.end_point.x(), self.end_point.y()

        return QRectF(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))

    def _select_shapes_in_box(self, selection_box: QRectF) -> None:
        """选择框内的图形（由外部实现）"""
        # 这个方法需要由外部调用者实现，因为需要访问所有图形
        pass

    def contains_point(self, point: QPointF, all_shapes: List[Shape]) -> List[Shape]:
        """获取包含指定点的图形"""
        # 从后往前遍历，后绘制的图形在上层
        for shape in reversed(all_shapes):
            if shape.contains_point(shape.map_from_scene(point)):
                return [shape]
        return []

    def get_nearest_control_point(
        self, point: QPointF, shape: Shape
    ) -> Tuple[QPointF, str]:
        """获取最近的控制点"""
        if not shape.selected:
            return None, None

        # 根据不同的图形类型返回不同的控制点
        if hasattr(shape, "rect"):
            # 矩形或椭圆
            rect = shape.bounding_rect()
            control_points = [
                (rect.topLeft(), "top-left"),
                (rect.topRight(), "top-right"),
                (rect.bottomRight(), "bottom-right"),
                (rect.bottomLeft(), "bottom-left"),
                (rect.center(), "center"),
            ]
        elif hasattr(shape, "line"):
            # 直线
            control_points = [
                (shape.line[0], "start"),
                (shape.line[1], "end"),
            ]
        elif hasattr(shape, "points"):
            # 多边形或折线
            control_points = [(p, f"point-{i}") for i, p in enumerate(shape.points)]
        else:
            return None, None

        # 找到最近的控制点
        min_dist = float("inf")
        nearest_point = None
        point_type = None

        for cp, cp_type in control_points:
            dist = (point - cp).manhattanLength()
            if dist < min_dist and dist < 10:  # 10像素的容差
                min_dist = dist
                nearest_point = cp
                point_type = cp_type

        return nearest_point, point_type

    def get_cursor_for_point(
        self, point: QPointF, all_shapes: List[Shape]
    ) -> Qt.CursorShape:
        """根据鼠标位置获取光标形状"""
        # 检查是否在选中的图形上
        for shape in self.shapes:
            if shape.contains_point(shape.map_from_scene(point)):
                # 检查是否在控制点上
                control_point, point_type = self.get_nearest_control_point(point, shape)
                if control_point:
                    if point_type in ["top-left", "bottom-right"]:
                        return Qt.SizeFDiagCursor
                    elif point_type in ["top-right", "bottom-left"]:
                        return Qt.SizeBDiagCursor
                    elif point_type in ["top", "bottom"]:
                        return Qt.SizeVerCursor
                    elif point_type in ["left", "right"]:
                        return Qt.SizeHorCursor
                    else:
                        return Qt.SizeAllCursor
                else:
                    return Qt.PointingHandCursor

        # 检查是否在任何图形上
        for shape in reversed(all_shapes):
            if shape.contains_point(shape.map_from_scene(point)):
                return Qt.PointingHandCursor

        return Qt.ArrowCursor

    def draw_selection_box(self, painter: QPainter) -> None:
        """绘制选择框"""
        if not self.is_selecting or not self.start_point or not self.end_point:
            return

        box = self.get_selection_box()

        # 绘制半透明的选择框
        painter.save()
        pen = QPen(QColor("#0078D4"))
        pen.setStyle(Qt.DashLine)
        pen.setWidth(1)
        painter.setPen(pen)
        brush = QBrush(QColor("#0078D4"))
        brush.setStyle(Qt.Dense4Pattern)
        painter.setBrush(brush)
        painter.setOpacity(0.3)

        painter.drawRect(box)

        # 绘制调整大小的手柄
        handle_size = 6
        corners = [
            box.topLeft(),
            box.topRight(),
            box.bottomRight(),
            box.bottomLeft(),
        ]

        for corner in corners:
            painter.setPen(QPen(QColor("#0078D4")))
            painter.setBrush(QBrush(QColor("#FFFFFF")))
            painter.drawRect(
                QRectF(
                    corner.x() - handle_size / 2,
                    corner.y() - handle_size / 2,
                    handle_size,
                    handle_size,
                )
            )

        painter.restore()


class SelectionCommand:
    """选择命令基类"""

    def __init__(self, selection_manager: SelectionManager):
        self.selection_manager = selection_manager
        self.previous_selection = set()

    def execute(self) -> None:
        """执行命令"""
        pass

    def undo(self) -> None:
        """撤销命令"""
        pass


class SelectCommand(SelectionCommand):
    """选择命令"""

    def __init__(self, selection_manager: SelectionManager, shapes: List[Shape]):
        super().__init__(selection_manager)
        self.shapes = shapes
        self.previous_selection = set(selection_manager.shapes)

    def execute(self) -> None:
        """执行选择"""
        self.selection_manager.clear_selection()
        for shape in self.shapes:
            self.selection_manager.add_shape(shape)

    def undo(self) -> None:
        """撤销选择"""
        self.selection_manager.clear_selection()
        for shape in self.previous_selection:
            self.selection_manager.add_shape(shape)
