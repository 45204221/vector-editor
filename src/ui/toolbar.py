"""工具栏"""

from PyQt5.QtWidgets import (QToolBar, QToolButton, QButtonGroup, QSpinBox,
                            QSizePolicy, QCheckBox, QWidget, QHBoxLayout, QLabel)
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import Qt, QSize

from core.selection import SelectionMode


class Toolbar(QToolBar):
    """主工具栏"""

    def __init__(self, canvas, graphics_view, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.graphics_view = graphics_view
        self.init_ui()

    def init_ui(self) -> None:
        """初始化工具栏"""
        self.setMovable(False)
        self.setIconSize(QSize(32, 32))
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)

        # 选择工具
        self.select_btn = QToolButton()
        self.select_btn.setText("选择")
        self.select_btn.setCheckable(True)
        self.select_btn.setChecked(True)
        self.select_btn.clicked.connect(self.on_select_tool)
        self.addWidget(self.select_btn)

        # 多选开关
        self.multi_btn = QToolButton()
        self.multi_btn.setText("多选")
        self.multi_btn.setCheckable(True)
        self.multi_btn.clicked.connect(self.on_multi_select_toggle)
        self.addWidget(self.multi_btn)

        # 分隔线
        self.addSeparator()

        # 绘制工具组
        self.drawing_group = QButtonGroup(self)
        self.drawing_group.setExclusive(True)

        self.rectangle_btn = QToolButton()
        self.rectangle_btn.setText("矩形")
        self.rectangle_btn.setCheckable(True)
        self.rectangle_btn.clicked.connect(self.on_rectangle_tool)
        self.addWidget(self.rectangle_btn)
        self.drawing_group.addButton(self.rectangle_btn)

        self.ellipse_btn = QToolButton()
        self.ellipse_btn.setText("椭圆")
        self.ellipse_btn.setCheckable(True)
        self.ellipse_btn.clicked.connect(self.on_ellipse_tool)
        self.addWidget(self.ellipse_btn)
        self.drawing_group.addButton(self.ellipse_btn)

        self.line_btn = QToolButton()
        self.line_btn.setText("直线")
        self.line_btn.setCheckable(True)
        self.line_btn.clicked.connect(self.on_line_tool)
        self.addWidget(self.line_btn)
        self.drawing_group.addButton(self.line_btn)

        self.polygon_btn = QToolButton()
        self.polygon_btn.setText("多边形")
        self.polygon_btn.setCheckable(True)
        self.polygon_btn.clicked.connect(self.on_polygon_tool)
        self.addWidget(self.polygon_btn)
        self.drawing_group.addButton(self.polygon_btn)

        self.polyline_btn = QToolButton()
        self.polyline_btn.setText("折线")
        self.polyline_btn.setCheckable(True)
        self.polyline_btn.clicked.connect(self.on_polyline_tool)
        self.addWidget(self.polyline_btn)
        self.drawing_group.addButton(self.polyline_btn)

        self.connection_btn = QToolButton()
        self.connection_btn.setText("连接线")
        self.connection_btn.setCheckable(True)
        self.connection_btn.clicked.connect(self.on_connection_tool)
        self.addWidget(self.connection_btn)
        self.drawing_group.addButton(self.connection_btn)

        self.text_btn = QToolButton()
        self.text_btn.setText("文字")
        self.text_btn.setCheckable(True)
        self.text_btn.clicked.connect(self.on_text_tool)
        self.addWidget(self.text_btn)
        self.drawing_group.addButton(self.text_btn)

        self.addSeparator()

        # 操作按钮
        delete_btn = QToolButton()
        delete_btn.setText("删除")
        delete_btn.clicked.connect(self.delete_selected)
        self.addWidget(delete_btn)

        duplicate_btn = QToolButton()
        duplicate_btn.setText("复制")
        duplicate_btn.clicked.connect(self.duplicate_selected)
        self.addWidget(duplicate_btn)

        # 分隔线
        self.addSeparator()

        # 网格设置
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        grid_label = QLabel("网格:")
        layout.addWidget(grid_label)

        self.grid_spinbox = QSpinBox()
        self.grid_spinbox.setRange(5, 50)
        self.grid_spinbox.setValue(10)
        self.grid_spinbox.setSuffix(" px")
        self.grid_spinbox.valueChanged.connect(self.set_grid_size)
        layout.addWidget(self.grid_spinbox)

        self.snap_checkbox = QCheckBox("吸附")
        self.snap_checkbox.setChecked(True)
        self.snap_checkbox.stateChanged.connect(self.set_snap_to_grid)
        layout.addWidget(self.snap_checkbox)

        self.addWidget(container)

    def delete_selected(self) -> None:
        """删除选中的图形"""
        self.canvas.delete_selected_shapes()

    def duplicate_selected(self) -> None:
        """复制选中的图形"""
        selected = self.canvas.get_selected_shapes()
        if selected:
            copied = self.canvas.copy_shapes(selected)
            self.canvas.paste_shapes(copied)

    def set_grid_size(self, size: int) -> None:
        """设置网格大小"""
        self.canvas.set_grid_size(size)

    def set_snap_to_grid(self, state: int) -> None:
        """设置是否吸附到网格"""
        self.canvas.set_snap_to_grid(state == Qt.Checked)

    def on_select_tool(self) -> None:
        """选择工具 — 单选模式"""
        self.graphics_view.set_tool('select')
        self.graphics_view.set_multi_select(False)
        self.select_btn.setChecked(True)
        self.multi_btn.setChecked(False)
        for btn in [self.rectangle_btn, self.ellipse_btn, self.line_btn,
                   self.polygon_btn, self.polyline_btn,
                   self.connection_btn, self.text_btn]:
            btn.setChecked(False)

    def on_multi_select_toggle(self) -> None:
        """切换多选模式"""
        if self.multi_btn.isChecked():
            self.graphics_view.set_multi_select(True)
            self.select_btn.setChecked(False)
            for btn in [self.rectangle_btn, self.ellipse_btn, self.line_btn,
                       self.polygon_btn, self.polyline_btn]:
                btn.setChecked(False)
            self.graphics_view.set_tool('select')
        else:
            self.graphics_view.set_multi_select(False)
            self.on_select_tool()

    def on_rectangle_tool(self) -> None:
        self.graphics_view.set_tool('rectangle')
        self.rectangle_btn.setChecked(True)
        self.select_btn.setChecked(False)
        self.multi_btn.setChecked(False)

    def on_ellipse_tool(self) -> None:
        self.graphics_view.set_tool('ellipse')
        self.ellipse_btn.setChecked(True)
        self.select_btn.setChecked(False)
        self.multi_btn.setChecked(False)

    def on_line_tool(self) -> None:
        self.graphics_view.set_tool('line')
        self.line_btn.setChecked(True)
        self.select_btn.setChecked(False)
        self.multi_btn.setChecked(False)

    def on_polygon_tool(self) -> None:
        self.graphics_view.set_tool('polygon')
        self.polygon_btn.setChecked(True)
        self.select_btn.setChecked(False)
        self.multi_btn.setChecked(False)

    def on_polyline_tool(self) -> None:
        self.graphics_view.set_tool('polyline')
        self.polyline_btn.setChecked(True)
        self.select_btn.setChecked(False)
        self.multi_btn.setChecked(False)

    def on_connection_tool(self) -> None:
        self.graphics_view.set_tool('connection')
        self.connection_btn.setChecked(True)
        self.select_btn.setChecked(False)
        self.multi_btn.setChecked(False)

    def on_text_tool(self) -> None:
        self.graphics_view.set_tool('text')
        self.text_btn.setChecked(True)
        self.select_btn.setChecked(False)
        self.multi_btn.setChecked(False)