"""属性面板"""

import math

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QColorDialog,
    QComboBox,
    QGroupBox,
    QCheckBox,
    QDoubleSpinBox,
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QColor, QPainter

from core.shape import ShapeType


# 样式字典映射
PEN_STYLE_MAP = {
    0: Qt.SolidLine,
    1: Qt.DashLine,
    2: Qt.DotLine,
    3: Qt.DashDotLine,
}

PEN_STYLE_TO_INDEX = {v: k for k, v in PEN_STYLE_MAP.items()}

BRUSH_STYLE_MAP = {
    0: Qt.SolidPattern,
    1: Qt.NoBrush,
    2: Qt.BDiagPattern,
    3: Qt.CrossPattern,
    4: Qt.Dense7Pattern,
}

BRUSH_STYLE_TO_INDEX = {v: k for k, v in BRUSH_STYLE_MAP.items()}


class PropertiesPanel(QWidget):
    """属性面板 — 位置、尺寸、样式、变换"""

    _NO_FILL = (ShapeType.LINE, ShapeType.POLYLINE, ShapeType.RESISTOR,
                ShapeType.CAPACITOR, ShapeType.INDUCTOR, ShapeType.GROUND,
                ShapeType.BATTERY, ShapeType.DIODE, ShapeType.CONNECTION, ShapeType.TEXT)

    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.current_shapes = []
        self._updating = False  # 信号锁，防止更新死循环
        self._history_timer = QTimer(self)
        self._history_timer.setSingleShot(True)
        self._history_timer.setInterval(350)
        self._history_timer.timeout.connect(self.canvas.commit_history_transaction)
        self.init_ui()

        if canvas:
            self.canvas.selection_changed.connect(self.on_selection_changed)

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # ── 基本属性组 ──
        basic_group = QGroupBox("基本属性")
        basic_layout = QVBoxLayout(basic_group)

        pos_layout = QHBoxLayout()
        pos_layout.addWidget(QLabel("X:"))
        self.x_spin = QSpinBox()
        self.x_spin.setRange(-9999, 9999)
        pos_layout.addWidget(self.x_spin)
        pos_layout.addWidget(QLabel("Y:"))
        self.y_spin = QSpinBox()
        self.y_spin.setRange(-9999, 9999)
        pos_layout.addWidget(self.y_spin)
        basic_layout.addLayout(pos_layout)

        size_layout = QHBoxLayout()
        size_layout.addWidget(QLabel("宽:"))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 9999)
        size_layout.addWidget(self.width_spin)
        size_layout.addWidget(QLabel("高:"))
        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, 9999)
        size_layout.addWidget(self.height_spin)
        basic_layout.addLayout(size_layout)

        basic_layout.addStretch()
        layout.addWidget(basic_group)

        # ── 样式组 ──
        style_group = QGroupBox("样式")
        style_layout = QVBoxLayout(style_group)

        # 线条颜色
        line_color_layout = QHBoxLayout()
        line_color_layout.addWidget(QLabel("线条:"))
        self.line_color_btn = ColorButton()
        line_color_layout.addWidget(self.line_color_btn)
        line_color_layout.addStretch()
        style_layout.addLayout(line_color_layout)

        # 线条宽度
        line_width_layout = QHBoxLayout()
        line_width_layout.addWidget(QLabel("线宽:"))
        self.line_width_spin = QSpinBox()
        self.line_width_spin.setRange(1, 20)
        self.line_width_spin.setValue(1)
        line_width_layout.addWidget(self.line_width_spin)
        line_width_layout.addWidget(QLabel("px"))
        line_width_layout.addStretch()
        style_layout.addLayout(line_width_layout)

        # 线条样式
        line_style_layout = QHBoxLayout()
        line_style_layout.addWidget(QLabel("线型:"))
        self.line_style_combo = QComboBox()
        self.line_style_combo.addItems(["实线", "虚线", "点线", "点划线"])
        line_style_layout.addWidget(self.line_style_combo)
        line_style_layout.addStretch()
        style_layout.addLayout(line_style_layout)

        stroke_geometry_layout = QHBoxLayout()
        stroke_geometry_layout.addWidget(QLabel("连接:"))
        self.line_join_combo = QComboBox()
        self.line_join_combo.addItems(["斜接", "斜角", "圆角"])
        stroke_geometry_layout.addWidget(self.line_join_combo)
        stroke_geometry_layout.addWidget(QLabel("端点:"))
        self.line_cap_combo = QComboBox()
        self.line_cap_combo.addItems(["平头", "方头", "圆头"])
        stroke_geometry_layout.addWidget(self.line_cap_combo)
        style_layout.addLayout(stroke_geometry_layout)

        # 字号（仅文字图形可用）
        font_size_layout = QHBoxLayout()
        font_size_layout.addWidget(QLabel("字号:"))
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 72)
        self.font_size_spin.setValue(16)
        self.font_size_spin.valueChanged.connect(self.on_font_size_changed)
        font_size_layout.addWidget(self.font_size_spin)
        font_size_layout.addWidget(QLabel("pt"))
        font_size_layout.addStretch()
        style_layout.addLayout(font_size_layout)

        # 不透明度
        opacity_layout = QHBoxLayout()
        opacity_layout.addWidget(QLabel("不透明度:"))
        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(10, 100)
        self.opacity_spin.setValue(100)
        self.opacity_spin.setSuffix("%")
        opacity_layout.addWidget(self.opacity_spin)
        opacity_layout.addStretch()
        style_layout.addLayout(opacity_layout)

        style_layout.addSpacing(10)

        # 填充颜色
        fill_color_layout = QHBoxLayout()
        fill_color_layout.addWidget(QLabel("填充:"))
        self.fill_color_btn = ColorButton()
        self.fill_color_btn.setColor(QColor("#FFFFFF"))
        fill_color_layout.addWidget(self.fill_color_btn)
        fill_color_layout.addStretch()
        style_layout.addLayout(fill_color_layout)

        # 填充样式
        fill_style_layout = QHBoxLayout()
        fill_style_layout.addWidget(QLabel("填充样式:"))
        self.fill_style_combo = QComboBox()
        self.fill_style_combo.addItems(["实心", "无填充", "斜线", "网格", "点"])
        fill_style_layout.addWidget(self.fill_style_combo)
        fill_style_layout.addStretch()
        style_layout.addLayout(fill_style_layout)

        style_layout.addStretch()
        layout.addWidget(style_group)

        # ── 变换组 ──
        transform_group = QGroupBox("变换")
        transform_layout = QVBoxLayout(transform_group)

        rotate_layout = QHBoxLayout()
        rotate_layout.addWidget(QLabel("旋转:"))
        self.rotate_spin = QSpinBox()
        self.rotate_spin.setRange(-360, 360)
        rotate_layout.addWidget(self.rotate_spin)
        rotate_layout.addWidget(QLabel("°"))
        rotate_layout.addStretch()
        transform_layout.addLayout(rotate_layout)

        scale_layout = QHBoxLayout()
        scale_layout.addWidget(QLabel("缩放:"))
        self.scale_x_spin = QSpinBox()
        self.scale_x_spin.setRange(10, 500)
        self.scale_x_spin.setValue(100)
        self.scale_x_spin.setSuffix("%")
        scale_layout.addWidget(self.scale_x_spin)
        scale_layout.addWidget(QLabel("×"))
        self.scale_y_spin = QSpinBox()
        self.scale_y_spin.setRange(10, 500)
        self.scale_y_spin.setValue(100)
        self.scale_y_spin.setSuffix("%")
        scale_layout.addWidget(self.scale_y_spin)
        scale_layout.addStretch()
        transform_layout.addLayout(scale_layout)

        transform_layout.addStretch()
        layout.addWidget(transform_group)

        # ── 引擎组件组 ──
        engine_group = QGroupBox("引擎组件")
        engine_layout = QVBoxLayout(engine_group)
        collision_layout = QHBoxLayout(); collision_layout.addWidget(QLabel("碰撞体:"))
        self.collider_combo = QComboBox(); self.collider_combo.addItems(["无", "AABB", "圆形"])
        collision_layout.addWidget(self.collider_combo); engine_layout.addLayout(collision_layout)
        self.rigid_enabled = QCheckBox("启用刚体")
        engine_layout.addWidget(self.rigid_enabled)
        body_layout = QHBoxLayout(); body_layout.addWidget(QLabel("质量:"))
        self.mass_spin = QDoubleSpinBox(); self.mass_spin.setRange(0.1, 1000); self.mass_spin.setValue(1); body_layout.addWidget(self.mass_spin)
        engine_layout.addLayout(body_layout)
        velocity_layout = QHBoxLayout(); velocity_layout.addWidget(QLabel("速度 X/Y:"))
        self.velocity_x_spin = QDoubleSpinBox(); self.velocity_x_spin.setRange(-2000, 2000); velocity_layout.addWidget(self.velocity_x_spin)
        self.velocity_y_spin = QDoubleSpinBox(); self.velocity_y_spin.setRange(-2000, 2000); velocity_layout.addWidget(self.velocity_y_spin)
        engine_layout.addLayout(velocity_layout)
        layout.addWidget(engine_group)

        layout.addStretch()
        self.setup_connections()

    def setup_connections(self) -> None:
        self.x_spin.valueChanged.connect(self.on_position_changed)
        self.y_spin.valueChanged.connect(self.on_position_changed)
        self.width_spin.valueChanged.connect(self.on_size_changed)
        self.height_spin.valueChanged.connect(self.on_size_changed)

        self.line_color_btn.colorChanged.connect(self.on_style_changed)
        self.line_width_spin.valueChanged.connect(self.on_style_changed)
        self.line_style_combo.currentIndexChanged.connect(self.on_style_changed)
        self.line_join_combo.currentIndexChanged.connect(self.on_style_changed)
        self.line_cap_combo.currentIndexChanged.connect(self.on_style_changed)
        self.opacity_spin.valueChanged.connect(self.on_style_changed)
        self.fill_color_btn.colorChanged.connect(self.on_style_changed)
        self.fill_style_combo.currentIndexChanged.connect(self.on_style_changed)

        self.rotate_spin.valueChanged.connect(self.on_transform_changed)
        self.scale_x_spin.valueChanged.connect(self.on_transform_changed)
        self.scale_y_spin.valueChanged.connect(self.on_transform_changed)
        self.collider_combo.currentIndexChanged.connect(self.on_engine_changed)
        self.rigid_enabled.toggled.connect(self.on_engine_changed)
        self.mass_spin.valueChanged.connect(self.on_engine_changed)
        self.velocity_x_spin.valueChanged.connect(self.on_engine_changed)
        self.velocity_y_spin.valueChanged.connect(self.on_engine_changed)

    def _begin_property_history(self) -> None:
        """合并连续 SpinBox/颜色变化为一条可撤销操作。"""
        self.canvas.begin_history_transaction("修改属性")
        self._history_timer.start()

    # ── 选择变化 ──

    def on_selection_changed(self) -> None:
        self.current_shapes = self.canvas.get_selected_shapes()
        self.update_properties()

    def update_properties(self) -> None:
        self._updating = True

        if not self.current_shapes:
            self.x_spin.setValue(0)
            self.y_spin.setValue(0)
            self.width_spin.setValue(0)
            self.height_spin.setValue(0)
            self._enable_fill_controls(True)
            self.font_size_spin.setEnabled(False)
            self._updating = False
            return

        shape = self.current_shapes[0]
        rect = shape.bounding_rect()
        style = shape.style
        fillable = shape.shape_type not in self._NO_FILL

        self.x_spin.setValue(int(rect.x()))
        self.y_spin.setValue(int(rect.y()))
        self.width_spin.setValue(int(rect.width()))
        self.height_spin.setValue(int(rect.height()))

        self.line_color_btn.setColor(QColor(style.pen_color))
        self.line_width_spin.setValue(int(style.pen_width))
        self.line_style_combo.setCurrentIndex(PEN_STYLE_TO_INDEX.get(style.pen_style, 0))
        self.line_join_combo.setCurrentIndex(
            {"miter": 0, "bevel": 1, "round": 2}.get(style.line_join, 0))
        self.line_cap_combo.setCurrentIndex(
            {"butt": 0, "square": 1, "round": 2}.get(style.line_cap, 0))
        self.opacity_spin.setValue(int(style.opacity * 100))

        is_text = shape.shape_type == ShapeType.TEXT
        self._enable_fill_controls(fillable)
        self.font_size_spin.setEnabled(is_text)
        if is_text:
            self.font_size_spin.setValue(shape.font_size)

        if fillable:
            self.fill_color_btn.setColor(QColor(style.brush_color))
            self.fill_style_combo.setCurrentIndex(BRUSH_STYLE_TO_INDEX.get(style.brush_style, 0))

        self.rotate_spin.setValue(self._get_rotation(shape))
        self.collider_combo.setCurrentIndex({"none": 0, "aabb": 1, "circle": 2}.get(shape.collider.type.value, 1))
        self.rigid_enabled.setChecked(shape.rigid_body.enabled)
        self.mass_spin.setValue(shape.rigid_body.mass)
        self.velocity_x_spin.setValue(shape.rigid_body.velocity_x)
        self.velocity_y_spin.setValue(shape.rigid_body.velocity_y)
        # 缩放值保持上次设置，不强制重置
        self._updating = False

    def _get_rotation(self, shape):
        """从 QTransform 提取当前旋转角度（度）"""
        t = shape.transform
        return round(math.degrees(math.atan2(t.m21(), t.m11())))

    def _enable_fill_controls(self, enabled: bool):
        """启用/禁用填充相关控件（直线和折线不可填充）"""
        self.fill_color_btn.setEnabled(enabled)
        self.fill_style_combo.setEnabled(enabled)

    def on_font_size_changed(self) -> None:
        if self._updating or not self.current_shapes:
            return
        self._begin_property_history()
        size = self.font_size_spin.value()
        for shape in self.current_shapes:
            if shape.shape_type == ShapeType.TEXT:
                shape.font_size = size
                shape.rect = shape._calc_rect(shape.rect.x(), shape.rect.y())
        self.canvas.update_world_state()

    # ── 位置 ──

    def on_position_changed(self) -> None:
        if self._updating or not self.current_shapes:
            return

        self._begin_property_history()
        shape = self.current_shapes[0]
        rect = shape.bounding_rect()
        cw = self.canvas.width
        ch = self.canvas.height

        # 钳制目标位置到画布边界内
        target_x = max(0.0, min(float(cw) - rect.width(), float(self.x_spin.value())))
        target_y = max(0.0, min(float(ch) - rect.height(), float(self.y_spin.value())))

        dx = target_x - rect.x()
        dy = target_y - rect.y()

        if dx != 0 or dy != 0:
            self.canvas.move_shapes(self.current_shapes, dx, dy)
            self.canvas.canvas_changed.emit()

    # ── 尺寸 ──

    def on_size_changed(self) -> None:
        if self._updating or not self.current_shapes:
            return

        self._begin_property_history()
        shape = self.current_shapes[0]
        if not hasattr(shape, "rect"):
            return

        rect = shape.bounding_rect()
        if rect.width() <= 0 or rect.height() <= 0:
            return

        cw = self.canvas.width
        ch = self.canvas.height
        center = rect.center()

        # 钳制宽高：以中心缩放，四边均不得超出画布
        max_w = min(2.0 * center.x(), 2.0 * (cw - center.x()))
        max_h = min(2.0 * center.y(), 2.0 * (ch - center.y()))
        new_w = max(1.0, min(float(self.width_spin.value()), max_w))
        new_h = max(1.0, min(float(self.height_spin.value()), max_h))

        sx = new_w / rect.width()
        sy = new_h / rect.height()

        if sx != 1.0 or sy != 1.0:
            self.canvas.scale_shapes(self.current_shapes, sx, sy, center)
            self.canvas.canvas_changed.emit()

        # 如果输入值被钳制，同步回 spinbox
        if int(new_w) != self.width_spin.value() or int(new_h) != self.height_spin.value():
            self._updating = True
            self.width_spin.setValue(int(new_w))
            self.height_spin.setValue(int(new_h))
            self._updating = False

    # ── 样式 ──

    def on_style_changed(self) -> None:
        if self._updating or not self.current_shapes:
            return

        self._begin_property_history()
        pen_color = self.line_color_btn.color().name()
        pen_width = self.line_width_spin.value()
        pen_style = PEN_STYLE_MAP.get(self.line_style_combo.currentIndex(), Qt.SolidLine)
        line_join = ("miter", "bevel", "round")[self.line_join_combo.currentIndex()]
        line_cap = ("butt", "square", "round")[self.line_cap_combo.currentIndex()]
        opacity = self.opacity_spin.value() / 100.0
        brush_color = self.fill_color_btn.color().name()
        brush_style = BRUSH_STYLE_MAP.get(self.fill_style_combo.currentIndex(), Qt.SolidPattern)

        for shape in self.current_shapes:
            shape.style.pen_color = pen_color
            shape.style.pen_width = pen_width
            shape.style.pen_style = pen_style
            shape.style.line_join = line_join
            shape.style.line_cap = line_cap
            shape.style.opacity = opacity
            # 直线和折线不应用填充
            if shape.shape_type not in self._NO_FILL:
                shape.style.brush_color = brush_color
                shape.style.brush_style = brush_style

        self.canvas.canvas_changed.emit()

    # ── 变换 ──

    def on_transform_changed(self) -> None:
        if self._updating or not self.current_shapes:
            return

        self._begin_property_history()
        rotation = self.rotate_spin.value()
        sx = self.scale_x_spin.value() / 100.0
        sy = self.scale_y_spin.value() / 100.0

        for shape in self.current_shapes:
            self.canvas._rebuild_transform(shape, rotation, sx, sy)

        self.canvas.update_world_state()

    def on_engine_changed(self) -> None:
        if self._updating or not self.current_shapes:
            return
        self._begin_property_history()
        from core.collision import ColliderType
        collider_types = [ColliderType.NONE, ColliderType.AABB, ColliderType.CIRCLE]
        for shape in self.current_shapes:
            shape.collider.type = collider_types[self.collider_combo.currentIndex()]
            shape.rigid_body.enabled = self.rigid_enabled.isChecked()
            shape.rigid_body.mass = self.mass_spin.value()
            shape.rigid_body.velocity_x = self.velocity_x_spin.value()
            shape.rigid_body.velocity_y = self.velocity_y_spin.value()
        self.canvas.update_world_state()

class ColorButton(QWidget):
    """颜色选择按钮"""

    colorChanged = pyqtSignal(QColor)

    def __init__(self, color=None, parent=None):
        super().__init__(parent)
        self._color = color or Qt.black
        self.setFixedSize(40, 30)
        self._pressed = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._color)
        if self._pressed:
            painter.setPen(Qt.black)
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def mousePressEvent(self, event):
        self._pressed = True
        self.update()

    def mouseReleaseEvent(self, event):
        self._pressed = False
        self.update()
        color = QColorDialog.getColor(self._color, self)
        if color.isValid():
            self.setColor(color)
            self.colorChanged.emit(color)

    def setColor(self, color):
        self._color = QColor(color)
        self.update()

    def color(self):
        return self._color
