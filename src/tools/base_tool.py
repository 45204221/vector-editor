"""工具基类"""

from abc import ABC, abstractmethod

from PyQt5.QtCore import QPointF, QRectF, Qt

from core.shape import ShapeStyle, ConnectionShape, TextShape


class Tool(ABC):
    """工具基类"""

    # 工具状态
    IDLE = 0      # 空闲状态
    ACTIVE = 1    # 活动状态
    DRAWING = 2   # 绘制状态

    def __init__(self, graphics_view):
        self.graphics_view = graphics_view
        self.canvas = graphics_view.canvas
        self.state = self.IDLE
        self.cursor = Qt.ArrowCursor

    @abstractmethod
    def mousePressEvent(self, event) -> None:
        """鼠标按下事件"""
        pass

    @abstractmethod
    def mouseReleaseEvent(self, event) -> None:
        """鼠标释放事件"""
        pass

    @abstractmethod
    def mouseMoveEvent(self, event) -> None:
        """鼠标移动事件"""
        pass

    def mouseDoubleClickEvent(self, event) -> None:
        """鼠标双击事件"""
        pass

    def hoverMoveEvent(self, event) -> None:
        """鼠标悬停移动事件"""
        pass

    def activate(self) -> None:
        """激活工具"""
        self.state = self.ACTIVE
        self.graphics_view.viewport().setCursor(self.cursor)

    def deactivate(self) -> None:
        """停用工具"""
        self.state = self.IDLE
        self.graphics_view.viewport().setCursor(Qt.ArrowCursor)

    def get_scene_pos(self, event) -> QPointF:
        """获取场景坐标 — 将 QMouseEvent 的 widget 坐标转换为场景坐标"""
        return self.graphics_view.mapToScene(event.pos())

    def get_mouse_pos(self, event) -> QPointF:
        """获取鼠标位置（带吸附）"""
        pos = self.get_scene_pos(event)
        if self.canvas.snap_to_grid:
            from ..core.transform import TransformUtils
            return TransformUtils.snap_to_grid(pos, self.canvas.grid_size)
        return pos

    def clamp_to_canvas(self, point: QPointF) -> QPointF:
        """将坐标钳制在画布边界内"""
        x = max(0.0, min(float(self.canvas.width), point.x()))
        y = max(0.0, min(float(self.canvas.height), point.y()))
        return QPointF(x, y)


class SelectTool(Tool):
    """选择工具"""

    def __init__(self, graphics_view):
        super().__init__(graphics_view)
        self.cursor = Qt.PointingHandCursor
        self.is_dragging = False
        self.drag_start_point = QPointF()
        self.selected_shapes = []
        self._resizing = False
        self._resize_edge = 0  # 0=right, 1=bottom, 2=corner

    def _get_resize_edge(self, shape, pos):
        """检测 pos 是否靠近选中文字图形边缘（10px容差）"""
        if not isinstance(shape, TextShape) or not shape.selected:
            return None
        br = shape.bounding_rect()
        near_right = abs(pos.x() - br.right()) < 10 and br.top() <= pos.y() <= br.bottom()
        near_bottom = abs(pos.y() - br.bottom()) < 10 and br.left() <= pos.x() <= br.right()
        if near_right and near_bottom: return 2
        if near_right: return 0
        if near_bottom: return 1
        return None

    def mousePressEvent(self, event) -> None:
        """鼠标按下"""
        if event.button() == Qt.LeftButton:
            pos = self.get_scene_pos(event)
            shape = self.graphics_view.hit_test_for_selection(pos, event.pos())
            multi = self.graphics_view.multi_select_mode

            # 检查是否拖边调整文字大小
            if not multi:
                sel = self.canvas.get_selected_shapes()
                if len(sel) == 1:
                    edge = self._get_resize_edge(sel[0], pos)
                    if edge is not None:
                        self.canvas.begin_history_transaction("调整文字大小")
                        self._resizing = True
                        self._resize_edge = edge
                        self.drag_start_point = pos
                        self.graphics_view.setDragMode(self.graphics_view.NoDrag)
                        return

            if multi or event.modifiers() & Qt.ShiftModifier:
                if shape:
                    self.canvas.toggle_selection(shape)
            else:
                if shape:
                    self.canvas.select_shape(shape)
                    self.canvas.begin_history_transaction("拖动图元")
                    self.is_dragging = True
                    self.drag_start_point = pos
                    self.graphics_view.setDragMode(self.graphics_view.NoDrag)
                else:
                    self.canvas.clear_selection()
                    self.graphics_view.setDragMode(self.graphics_view.RubberBandDrag)

    def mouseReleaseEvent(self, event) -> None:
        """鼠标释放"""
        if event.button() == Qt.LeftButton:
            if self.is_dragging or self._resizing:
                self.canvas.commit_history_transaction()
            self.is_dragging = False
            self._resizing = False
            self.graphics_view.setDragMode(self.graphics_view.RubberBandDrag)

    def mouseMoveEvent(self, event) -> None:
        current_pos = self.get_scene_pos(event)

        if self._resizing:
            sel = self.canvas.get_selected_shapes()
            if sel:
                shape = sel[0]
                dx = current_pos.x() - self.drag_start_point.x()
                dy = current_pos.y() - self.drag_start_point.y()
                if self._resize_edge in (0, 2):
                    max_width = max(20, self.canvas.width - shape.rect.x())
                    shape.rect.setWidth(min(max_width, max(20, shape.rect.width() + dx)))
                if self._resize_edge in (1, 2):
                    max_height = max(16, self.canvas.height - shape.rect.y())
                    shape.rect.setHeight(min(max_height, max(16, shape.rect.height() + dy)))
                self.drag_start_point = current_pos
                self.canvas.canvas_changed.emit()
            return

        if self.is_dragging and event.buttons() & Qt.LeftButton:
            dx = current_pos.x() - self.drag_start_point.x()
            dy = current_pos.y() - self.drag_start_point.y()
            selected = self.canvas.get_selected_shapes()
            if selected:
                dx, dy = self._clamp_move_delta(selected, dx, dy)
                if dx != 0 or dy != 0:
                    self.canvas.move_shapes(selected, dx, dy)
                self.drag_start_point = current_pos

    def _clamp_move_delta(self, shapes, dx, dy):
        """钳制移动偏移量，确保所有选中图形的边界在画布内"""
        return self.canvas._clamp_group_delta(shapes, dx, dy)

    def mouseDoubleClickEvent(self, event) -> None:
        """鼠标双击 - 编辑图形"""
        pos = self.get_scene_pos(event)
        shape = self.graphics_view.hit_test_for_selection(pos, event.pos())
        if shape:
            # 这里可以触发编辑功能
            pass


class DrawTool(Tool):
    """绘制工具基类"""

    def __init__(self, graphics_view):
        super().__init__(graphics_view)
        self.cursor = Qt.CrossCursor
        self.start_point = QPointF()
        self.temp_shape = None

    def mousePressEvent(self, event) -> None:
        """鼠标按下 - 开始绘制"""
        if event.button() == Qt.LeftButton:
            self.start_point = self.clamp_to_canvas(self.get_scene_pos(event))
            self.state = self.DRAWING

    def mouseMoveEvent(self, event) -> None:
        """鼠标移动 - 更新临时图形"""
        if self.state == self.DRAWING:
            end_point = self.clamp_to_canvas(self.get_scene_pos(event))
            self.update_temp_shape(self.start_point, end_point)

    def mouseReleaseEvent(self, event) -> None:
        """鼠标释放 - 完成绘制"""
        if event.button() == Qt.LeftButton and self.state == self.DRAWING:
            end_point = self.clamp_to_canvas(self.get_scene_pos(event))
            
            # 移除临时图形
            if self.temp_shape:
                self.canvas.remove_preview_shape(self.temp_shape)
                self.temp_shape = None

            final_shape = self.create_shape(self.start_point, end_point)

            if final_shape:
                self.canvas.add_shape(final_shape)
                
            self.state = self.IDLE
            self.graphics_view.update_scene()

    def deactivate(self) -> None:
        if self.temp_shape:
            self.canvas.remove_preview_shape(self.temp_shape)
            self.temp_shape = None
        super().deactivate()
            
    def create_shape(self, start, end):
        """创建图形（由子类实现）"""
        pass

    def update_temp_shape(self, start, end):
        """更新临时图形（由子类实现）"""
        pass


class RectangleTool(DrawTool):
    """矩形工具"""

    def create_shape(self, start, end):
        """创建矩形"""
        x = min(start.x(), end.x())
        y = min(start.y(), end.y())
        width = abs(end.x() - start.x())
        height = abs(end.y() - start.y())

        return self.canvas.create_rectangle(x, y, width, height)

    def update_temp_shape(self, start, end):
        """更新临时矩形"""
        x = min(start.x(), end.x())
        y = min(start.y(), end.y())
        width = abs(end.x() - start.x())
        height = abs(end.y() - start.y())

        if self.temp_shape:
            self.temp_shape.rect = QRectF(x, y, width, height)
        else:
            self.temp_shape = self.canvas.create_rectangle(x, y, width, height)
            self.temp_shape.style = ShapeStyle(
                pen_color="#FF0000",
                brush_color="#FF0000",
                opacity=0.3
            )
            self.canvas.add_preview_shape(self.temp_shape)

        self.graphics_view.update_scene()


class EllipseTool(DrawTool):
    """椭圆工具"""

    def create_shape(self, start, end):
        """创建椭圆"""
        x = min(start.x(), end.x())
        y = min(start.y(), end.y())
        width = abs(end.x() - start.x())
        height = abs(end.y() - start.y())

        return self.canvas.create_ellipse(x, y, width, height)

    def update_temp_shape(self, start, end):
        """更新临时椭圆"""
        # 创建临时椭圆
        x = min(start.x(), end.x())
        y = min(start.y(), end.y())
        width = abs(end.x() - start.x())
        height = abs(end.y() - start.y())

        # 更新或创建临时图形
        if self.temp_shape:
            self.temp_shape.rect = QRectF(x, y, width, height)
        else:
            self.temp_shape = self.canvas.create_ellipse(x, y, width, height)
            self.temp_shape.style = ShapeStyle(
                pen_color="#FF0000",
                brush_color="#FF0000",
                opacity=0.3
            )
            self.canvas.add_preview_shape(self.temp_shape)

        # 强制更新场景
        self.graphics_view.update_scene()


class LineTool(DrawTool):
    """直线工具"""

    def create_shape(self, start, end):
        """创建直线"""
        return self.canvas.create_line(start.x(), start.y(), end.x(), end.y())

    def update_temp_shape(self, start, end):
        """更新临时直线"""
        # 更新或创建临时图形
        if self.temp_shape:
            self.temp_shape.line = (start, end)
        else:
            self.temp_shape = self.canvas.create_line(start.x(), start.y(), end.x(), end.y())
            self.temp_shape.style = ShapeStyle(
                pen_color="#FF0000",
                opacity=0.8
            )
            self.canvas.add_preview_shape(self.temp_shape)

        # 强制更新场景
        self.graphics_view.update_scene()


class DiamondTool(DrawTool):
    """菱形工具"""

    def create_shape(self, start, end):
        x = min(start.x(), end.x())
        y = min(start.y(), end.y())
        w = abs(end.x() - start.x())
        h = abs(end.y() - start.y())
        return self.canvas.create_diamond(x, y, w, h)

    def update_temp_shape(self, start, end):
        x = min(start.x(), end.x())
        y = min(start.y(), end.y())
        w = abs(end.x() - start.x())
        h = abs(end.y() - start.y())
        if self.temp_shape:
            self.temp_shape.rect = QRectF(x, y, w, h)
        else:
            self.temp_shape = self.canvas.create_diamond(x, y, w, h)
            self.temp_shape.style = ShapeStyle(pen_color="#FF0000", brush_color="#FF0000", opacity=0.3)
            self.canvas.add_preview_shape(self.temp_shape)
        self.graphics_view.update_scene()


class RoundedRectTool(DrawTool):
    """圆角矩形工具"""

    def create_shape(self, start, end):
        x = min(start.x(), end.x())
        y = min(start.y(), end.y())
        w = abs(end.x() - start.x())
        h = abs(end.y() - start.y())
        return self.canvas.create_rounded_rect(x, y, w, h)

    def update_temp_shape(self, start, end):
        x = min(start.x(), end.x())
        y = min(start.y(), end.y())
        w = abs(end.x() - start.x())
        h = abs(end.y() - start.y())
        if self.temp_shape:
            self.temp_shape.rect = QRectF(x, y, w, h)
        else:
            self.temp_shape = self.canvas.create_rounded_rect(x, y, w, h)
            self.temp_shape.style = ShapeStyle(pen_color="#FF0000", brush_color="#FF0000", opacity=0.3)
            self.canvas.add_preview_shape(self.temp_shape)
        self.graphics_view.update_scene()


class ParallelogramTool(DrawTool):
    """平行四边形工具"""

    def create_shape(self, start, end):
        x = min(start.x(), end.x())
        y = min(start.y(), end.y())
        w = abs(end.x() - start.x())
        h = abs(end.y() - start.y())
        return self.canvas.create_parallelogram(x, y, w, h)

    def update_temp_shape(self, start, end):
        x = min(start.x(), end.x())
        y = min(start.y(), end.y())
        w = abs(end.x() - start.x())
        h = abs(end.y() - start.y())
        if self.temp_shape:
            self.temp_shape.rect = QRectF(x, y, w, h)
        else:
            self.temp_shape = self.canvas.create_parallelogram(x, y, w, h)
            self.temp_shape.style = ShapeStyle(pen_color="#FF0000", brush_color="#FF0000", opacity=0.3)
            self.canvas.add_preview_shape(self.temp_shape)
        self.graphics_view.update_scene()


class ResistorTool(DrawTool):
    def create_shape(self, start, end):
        x = min(start.x(), end.x()); y = min(start.y(), end.y())
        return self.canvas.create_resistor(x, y, abs(end.x() - start.x()), abs(end.y() - start.y()))

    def update_temp_shape(self, start, end):
        x = min(start.x(), end.x()); y = min(start.y(), end.y()); w = abs(end.x() - start.x()); h = abs(end.y() - start.y())
        if self.temp_shape:
            self.temp_shape.rect = QRectF(x, y, w, h)
        else:
            self.temp_shape = self.canvas.create_resistor(x, y, w, h)
            self.temp_shape.style = ShapeStyle(pen_color="#FF0000", opacity=0.8)
            self.canvas.add_preview_shape(self.temp_shape)
        self.graphics_view.update_scene()


class CapacitorTool(DrawTool):
    def create_shape(self, start, end):
        x = min(start.x(), end.x()); y = min(start.y(), end.y())
        return self.canvas.create_capacitor(x, y, abs(end.x() - start.x()), abs(end.y() - start.y()))

    def update_temp_shape(self, start, end):
        x = min(start.x(), end.x()); y = min(start.y(), end.y()); w = abs(end.x() - start.x()); h = abs(end.y() - start.y())
        if self.temp_shape:
            self.temp_shape.rect = QRectF(x, y, w, h)
        else:
            self.temp_shape = self.canvas.create_capacitor(x, y, w, h)
            self.temp_shape.style = ShapeStyle(pen_color="#FF0000", opacity=0.8)
            self.canvas.add_preview_shape(self.temp_shape)
        self.graphics_view.update_scene()


class InductorTool(DrawTool):
    def create_shape(self, start, end):
        x = min(start.x(), end.x()); y = min(start.y(), end.y())
        return self.canvas.create_inductor(x, y, abs(end.x() - start.x()), abs(end.y() - start.y()))

    def update_temp_shape(self, start, end):
        x = min(start.x(), end.x()); y = min(start.y(), end.y()); w = abs(end.x() - start.x()); h = abs(end.y() - start.y())
        if self.temp_shape:
            self.temp_shape.rect = QRectF(x, y, w, h)
        else:
            self.temp_shape = self.canvas.create_inductor(x, y, w, h)
            self.temp_shape.style = ShapeStyle(pen_color="#FF0000", opacity=0.8)
            self.canvas.add_preview_shape(self.temp_shape)
        self.graphics_view.update_scene()


class GroundTool(DrawTool):
    def create_shape(self, start, end):
        x = min(start.x(), end.x()); y = min(start.y(), end.y())
        return self.canvas.create_ground(x, y, abs(end.x() - start.x()), abs(end.y() - start.y()))

    def update_temp_shape(self, start, end):
        x = min(start.x(), end.x()); y = min(start.y(), end.y()); w = abs(end.x() - start.x()); h = abs(end.y() - start.y())
        if self.temp_shape:
            self.temp_shape.rect = QRectF(x, y, w, h)
        else:
            self.temp_shape = self.canvas.create_ground(x, y, w, h)
            self.temp_shape.style = ShapeStyle(pen_color="#FF0000", opacity=0.8)
            self.canvas.add_preview_shape(self.temp_shape)
        self.graphics_view.update_scene()


class BatteryTool(DrawTool):
    def create_shape(self, start, end):
        x = min(start.x(), end.x()); y = min(start.y(), end.y())
        return self.canvas.create_battery(x, y, abs(end.x() - start.x()), abs(end.y() - start.y()))

    def update_temp_shape(self, start, end):
        x = min(start.x(), end.x()); y = min(start.y(), end.y()); w = abs(end.x() - start.x()); h = abs(end.y() - start.y())
        if self.temp_shape:
            self.temp_shape.rect = QRectF(x, y, w, h)
        else:
            self.temp_shape = self.canvas.create_battery(x, y, w, h)
            self.temp_shape.style = ShapeStyle(pen_color="#FF0000", opacity=0.8)
            self.canvas.add_preview_shape(self.temp_shape)
        self.graphics_view.update_scene()


class DiodeTool(DrawTool):
    def create_shape(self, start, end):
        x = min(start.x(), end.x()); y = min(start.y(), end.y())
        return self.canvas.create_diode(x, y, abs(end.x() - start.x()), abs(end.y() - start.y()))

    def update_temp_shape(self, start, end):
        x = min(start.x(), end.x()); y = min(start.y(), end.y()); w = abs(end.x() - start.x()); h = abs(end.y() - start.y())
        if self.temp_shape:
            self.temp_shape.rect = QRectF(x, y, w, h)
        else:
            self.temp_shape = self.canvas.create_diode(x, y, w, h)
            self.temp_shape.style = ShapeStyle(pen_color="#FF0000", opacity=0.8)
            self.canvas.add_preview_shape(self.temp_shape)
        self.graphics_view.update_scene()


class OrgNodeTool(DrawTool):
    def create_shape(self, start, end):
        x = min(start.x(), end.x()); y = min(start.y(), end.y())
        return self.canvas.create_org_node(x, y, abs(end.x() - start.x()), abs(end.y() - start.y()))

    def update_temp_shape(self, start, end):
        x = min(start.x(), end.x()); y = min(start.y(), end.y()); w = abs(end.x() - start.x()); h = abs(end.y() - start.y())
        if self.temp_shape:
            self.temp_shape.rect = QRectF(x, y, w, h)
        else:
            self.temp_shape = self.canvas.create_org_node(x, y, w, h)
            self.temp_shape.style = ShapeStyle(pen_color="#FF0000", brush_color="#FF0000", opacity=0.3)
            self.canvas.add_preview_shape(self.temp_shape)
        self.graphics_view.update_scene()


class PolygonTool(DrawTool):
    """多边形工具 — 逐顶点点击构建，双击闭合"""

    def __init__(self, graphics_view):
        super().__init__(graphics_view)
        self.vertices = []          # 已确认的顶点
        self.preview_shape = None   # 画布中的临时预览线

    def mousePressEvent(self, event):
        """鼠标按下 — 添加顶点"""
        if event.button() != Qt.LeftButton:
            return

        pos = self.clamp_to_canvas(self.get_scene_pos(event))

        if self.state == self.DRAWING:
            self.vertices.append(pos)
            self._update_preview()
        else:
            self.vertices = [pos]
            self.state = self.DRAWING

    def mouseMoveEvent(self, event):
        """鼠标移动 — 从最后一个顶点到鼠标位置画橡皮筋"""
        if self.state == self.DRAWING and self.vertices:
            pos = self.clamp_to_canvas(self.get_scene_pos(event))
            self._update_preview_with_rubber_band(pos)

    def mouseReleaseEvent(self, event):
        """鼠标释放 — 不自动闭合，由双击决定闭合时机"""
        pass

    def mouseDoubleClickEvent(self, event):
        """双击 — 闭合多边形（至少 3 个顶点）"""
        if self.state == self.DRAWING and len(self.vertices) >= 3:
            self._finish_polygon()

    def _ensure_preview_shape(self, points):
        """确保预览图形存在并更新其顶点"""
        if self.preview_shape:
            self.preview_shape.points = points
        else:
            self.preview_shape = self.canvas.create_polyline(points)
            self.preview_shape.style = ShapeStyle(
                pen_color="#0000FF",
                pen_width=2,
            )
            self.canvas.add_preview_shape(self.preview_shape)

    def _update_preview(self):
        """更新预览 — 只显示已确认顶点之间的边"""
        if len(self.vertices) >= 2:
            self._ensure_preview_shape(self.vertices[:])
        self.graphics_view.update_scene()

    def _update_preview_with_rubber_band(self, mouse_pos):
        """更新预览 — 显示已确认边 + 到鼠标位置的橡皮筋"""
        points = self.vertices + [mouse_pos]
        self._ensure_preview_shape(points)
        self.graphics_view.update_scene()

    def _finish_polygon(self):
        """闭合多边形"""
        if self.preview_shape:
            self.canvas.remove_preview_shape(self.preview_shape)
            self.preview_shape = None

        if len(self.vertices) >= 3:
            polygon_shape = self.canvas.create_polygon(self.vertices)
            if polygon_shape:
                self.canvas.add_shape(polygon_shape)

        self.state = self.IDLE
        self.vertices = []
        self.graphics_view.update_scene()

    def deactivate(self):
        """停用工具 — 取消进行中的多边形"""
        super().deactivate()
        if self.preview_shape:
            self.canvas.remove_preview_shape(self.preview_shape)
            self.preview_shape = None
        if self.state == self.DRAWING:
            self.state = self.IDLE
            self.vertices = []
            self.graphics_view.update_scene()


class PolylineTool(DrawTool):
    """折线工具 — 逐顶点点击构建，双击完成（不闭合）"""

    def __init__(self, graphics_view):
        super().__init__(graphics_view)
        self.vertices = []          # 已确认的顶点
        self.preview_shape = None   # 画布中的临时预览线

    def mousePressEvent(self, event):
        """鼠标按下 — 添加顶点"""
        if event.button() != Qt.LeftButton:
            return

        pos = self.clamp_to_canvas(self.get_scene_pos(event))

        if self.state == self.DRAWING:
            self.vertices.append(pos)
            self._update_preview()
        else:
            self.vertices = [pos]
            self.state = self.DRAWING

    def mouseMoveEvent(self, event):
        """鼠标移动 — 橡皮筋预览"""
        if self.state == self.DRAWING and self.vertices:
            pos = self.clamp_to_canvas(self.get_scene_pos(event))
            self._update_preview_with_rubber_band(pos)

    def mouseReleaseEvent(self, event):
        """鼠标释放 — 不自动完成，由双击决定完成时机"""
        pass

    def mouseDoubleClickEvent(self, event):
        """双击 — 完成折线（至少 2 个顶点）"""
        if self.state == self.DRAWING and len(self.vertices) >= 2:
            self._finish_polyline()

    def _ensure_preview_shape(self, points):
        """确保预览图形存在并更新其顶点"""
        if self.preview_shape:
            self.preview_shape.points = points
        else:
            self.preview_shape = self.canvas.create_polyline(points)
            self.preview_shape.style = ShapeStyle(
                pen_color="#0000FF",
                pen_width=2,
            )
            self.canvas.add_preview_shape(self.preview_shape)

    def _update_preview(self):
        """更新预览 — 只显示已确认边"""
        if len(self.vertices) >= 2:
            self._ensure_preview_shape(self.vertices[:])
        self.graphics_view.update_scene()

    def _update_preview_with_rubber_band(self, mouse_pos):
        """更新预览 — 已确认边 + 橡皮筋"""
        points = self.vertices + [mouse_pos]
        self._ensure_preview_shape(points)
        self.graphics_view.update_scene()

    def _finish_polyline(self):
        """完成折线"""
        if self.preview_shape:
            self.canvas.remove_preview_shape(self.preview_shape)
            self.preview_shape = None

        if len(self.vertices) >= 2:
            polyline_shape = self.canvas.create_polyline(self.vertices)
            if polyline_shape:
                self.canvas.add_shape(polyline_shape)

        self.state = self.IDLE
        self.vertices = []
        self.graphics_view.update_scene()

    def deactivate(self):
        """停用工具 — 取消进行中的折线"""
        super().deactivate()
        if self.preview_shape:
            self.canvas.remove_preview_shape(self.preview_shape)
            self.preview_shape = None
        if self.state == self.DRAWING:
            self.state = self.IDLE
            self.vertices = []
            self.graphics_view.update_scene()


class ConnectionTool(Tool):
    """连接线工具——点击图形任意位置→拖动→松手到另一图形，自动选择最佳锚点"""

    def __init__(self, graphics_view):
        super().__init__(graphics_view)
        self.cursor = Qt.CrossCursor
        self.source_shape = None
        self._temp_line = None

    @staticmethod
    def _best_anchor_pair(a, b):
        """根据两图形中心相对位置选择锚点对 (a_anchor, b_anchor)"""
        ca = a.bounding_rect().center()
        cb = b.bounding_rect().center()
        dx, dy = cb.x() - ca.x(), cb.y() - ca.y()
        if abs(dx) > abs(dy):
            return (1, 3) if dx > 0 else (3, 1)   # 水平：右→左 或 左→右
        else:
            return (2, 0) if dy > 0 else (0, 2)   # 垂直：下→上 或 上→下

    def _update_temp_line(self, p1, p2):
        if self._temp_line:
            self._temp_line.line = (p1, p2)
        else:
            self._temp_line = self.canvas.create_line(p1.x(), p1.y(), p2.x(), p2.y())
            self._temp_line.style = ShapeStyle(pen_color="#FF6600", pen_width=2, opacity=0.8)
            self.canvas.add_preview_shape(self._temp_line)

    def _cleanup_temp_line(self):
        if self._temp_line:
            self.canvas.remove_preview_shape(self._temp_line)
            self._temp_line = None

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        pos = self.get_scene_pos(event)
        shape = self.canvas.hit_test(pos)
        if shape and not isinstance(shape, ConnectionShape):
            self.source_shape = shape
            self.state = self.DRAWING
            pt = shape.bounding_rect().center()
            self._update_temp_line(pt, pt)
            self.graphics_view.update_scene()

    def mouseMoveEvent(self, event):
        if self.state == self.DRAWING and self.source_shape:
            src = self.source_shape.bounding_rect().center()
            self._update_temp_line(src, self.get_scene_pos(event))
            self.graphics_view.update_scene()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self.state != self.DRAWING:
            return
        self._cleanup_temp_line()
        pos = self.get_scene_pos(event)
        target = self.canvas.hit_test(pos)
        if (target and target != self.source_shape
                and not isinstance(target, ConnectionShape)):
            sa, ta = self._best_anchor_pair(self.source_shape, target)
            conn = self.canvas.create_connection(self.source_shape, sa, target, ta)
            self.canvas.add_shape(conn)
        self.state = self.IDLE
        self.source_shape = None
        self.graphics_view.update_scene()

    def deactivate(self):
        super().deactivate()
        self._cleanup_temp_line()
        self.state = self.IDLE


class TextTool(DrawTool):
    """文字工具——拖动创建文本框，松手输入文字"""

    def __init__(self, graphics_view):
        super().__init__(graphics_view)
        self.cursor = Qt.IBeamCursor

    def update_temp_shape(self, start, end):
        x = min(start.x(), end.x()); y = min(start.y(), end.y())
        w = abs(end.x() - start.x()); h = abs(end.y() - start.y())
        if self.temp_shape:
            self.temp_shape.rect = QRectF(x, y, w, h)
        else:
            self.temp_shape = self.canvas.create_rectangle(x, y, w, h)
            self.temp_shape.style = ShapeStyle(pen_color="#FF0000", brush_color="#FF0000", opacity=0.2)
            self.canvas.add_preview_shape(self.temp_shape)
        self.graphics_view.update_scene()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self.state != self.DRAWING:
            return
        end_point = self.get_scene_pos(event)
        if self.temp_shape:
            self.canvas.remove_preview_shape(self.temp_shape)
            self.temp_shape = None
        from PyQt5.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(
            self.graphics_view, "输入文字", "请输入文字内容:")
        if ok:
            x = min(self.start_point.x(), end_point.x())
            y = min(self.start_point.y(), end_point.y())
            w = max(40, abs(end_point.x() - self.start_point.x()))
            h = max(20, abs(end_point.y() - self.start_point.y()))
            shape = self.canvas.create_text(x, y, text)
            shape.rect = QRectF(x, y, w, h)
            self.canvas.add_shape(shape)
        self.state = self.IDLE
        self.graphics_view.update_scene()
