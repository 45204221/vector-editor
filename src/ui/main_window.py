"""主窗口"""

from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QToolBar,
    QAction,
    QActionGroup,
    QMenu,
    QToolButton,
    QStatusBar,
    QDockWidget,
    QFileDialog,
    QMessageBox,
    QTabWidget,
    QScrollArea,
    QFrame,
)
from PyQt5.QtCore import Qt, QSize, QTimer
from PyQt5.QtGui import QKeySequence

from core.canvas import Canvas
from widgets.graphics_view import GraphicsView
from .toolbar import Toolbar
from .properties import PropertiesPanel
from .layer_panel import LayerPanel
from .engine_lab_window import EngineLabWindow


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.canvas = Canvas()
        self._clipboard = []  # 剪贴板：存储复制的图形 dict 数据
        self.init_ui()
        self.setup_connections()
        self.setWindowTitle("矢量图形编辑器")
        self.setMinimumSize(900, 600)
        self.resize(1200, 800)

    def init_ui(self) -> None:
        """初始化用户界面"""
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        # central_widget.installEventFilter(self)

        # 创建主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 创建图形视图
        self.graphics_view = GraphicsView(self.canvas)
        main_layout.addWidget(self.graphics_view)

        # 创建工具栏
        self.toolbar = Toolbar(self.canvas, self.graphics_view)
        main_layout.addWidget(self.toolbar)

        # 创建菜单栏
        self.create_menu_bar()

        # 创建工具栏
        self.create_toolbar()

        # 创建属性面板
        self.create_properties_panel()

        # 创建状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

    def create_menu_bar(self) -> None:
        """创建菜单栏"""
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")

        new_action = QAction("新建(&N)", self)
        new_action.setShortcut(QKeySequence.New)
        new_action.triggered.connect(self.new_file)
        file_menu.addAction(new_action)

        file_menu.addSeparator()

        open_action = QAction("打开(&O)...", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self.open_file)
        file_menu.addAction(open_action)

        save_action = QAction("保存(&S)...", self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self.save_file)
        file_menu.addAction(save_action)

        save_as_action = QAction("另存为(&A)...", self)
        save_as_action.setShortcut(QKeySequence.SaveAs)
        save_as_action.triggered.connect(self.save_file_as)
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()

        export_svg_action = QAction("导出 SVG...", self)
        export_svg_action.triggered.connect(self.export_svg)
        file_menu.addAction(export_svg_action)

        export_png_action = QAction("导出 PNG...", self)
        export_png_action.triggered.connect(self.export_png)
        file_menu.addAction(export_png_action)

        file_menu.addSeparator()

        exit_action = QAction("退出(&X)", self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 编辑菜单
        edit_menu = menubar.addMenu("编辑(&E)")

        self.undo_action = QAction("撤销(&U)", self)
        self.undo_action.setShortcut(QKeySequence.Undo)
        self.undo_action.triggered.connect(self.undo)
        edit_menu.addAction(self.undo_action)

        self.redo_action = QAction("重做(&R)", self)
        self.redo_action.setShortcut(QKeySequence.Redo)
        self.redo_action.triggered.connect(self.redo)
        edit_menu.addAction(self.redo_action)

        edit_menu.addSeparator()

        self.cut_action = QAction("剪切(&T)", self)
        self.cut_action.setShortcut(QKeySequence.Cut)
        self.cut_action.triggered.connect(self.cut)
        edit_menu.addAction(self.cut_action)

        self.copy_action = QAction("复制(&C)", self)
        self.copy_action.setShortcut(QKeySequence.Copy)
        self.copy_action.triggered.connect(self.copy)
        edit_menu.addAction(self.copy_action)

        self.paste_action = QAction("粘贴(&P)", self)
        self.paste_action.setShortcut(QKeySequence.Paste)
        self.paste_action.triggered.connect(self.paste)
        edit_menu.addAction(self.paste_action)

        self.delete_action = QAction("删除(&D)", self)
        self.delete_action.setShortcut(QKeySequence.Delete)
        self.delete_action.triggered.connect(self.delete)
        edit_menu.addAction(self.delete_action)

        # 视图菜单
        self.view_menu = menubar.addMenu("视图(&V)")

        zoom_in_action = QAction("放大(&I)", self)
        zoom_in_action.setShortcut(QKeySequence.ZoomIn)
        zoom_in_action.triggered.connect(self.zoom_in)
        self.view_menu.addAction(zoom_in_action)

        zoom_out_action = QAction("缩小(&O)", self)
        zoom_out_action.setShortcut(QKeySequence.ZoomOut)
        zoom_out_action.triggered.connect(self.zoom_out)
        self.view_menu.addAction(zoom_out_action)

        reset_zoom_action = QAction("重置缩放(&R)", self)
        reset_zoom_action.setShortcut("Ctrl+0")
        reset_zoom_action.triggered.connect(self.reset_zoom)
        self.view_menu.addAction(reset_zoom_action)

        self.view_menu.addSeparator()

        fit_window_action = QAction("适应窗口(&F)", self)
        fit_window_action.setShortcut("F")
        fit_window_action.triggered.connect(self.fit_to_window)
        self.view_menu.addAction(fit_window_action)

        self.view_menu.addSeparator()

        grid_action = QAction("显示网格(&G)", self)
        grid_action.setCheckable(True)
        grid_action.setChecked(True)
        grid_action.triggered.connect(self.toggle_grid)
        self.view_menu.addAction(grid_action)

        snap_action = QAction("吸附到网格(&N)", self)
        snap_action.setCheckable(True)
        snap_action.setChecked(True)
        snap_action.triggered.connect(self.toggle_snap)
        self.view_menu.addAction(snap_action)

        self.view_menu.addSeparator()
        engine_lab_action = QAction("打开引擎实验室", self)
        engine_lab_action.triggered.connect(self.show_pipeline_panel)
        self.view_menu.addAction(engine_lab_action)

        engine_menu = menubar.addMenu("引擎展示(&E)")
        self.engine_menu = engine_menu
        collision_action = QAction("显示碰撞/物理调试", self)
        collision_action.setCheckable(True); collision_action.setChecked(True)
        collision_action.toggled.connect(self.set_engine_debug)
        engine_menu.addAction(collision_action)
        physics_action = QAction("运行刚体模拟", self)
        physics_action.setCheckable(True)
        physics_action.toggled.connect(self.graphics_view.set_physics_running)
        engine_menu.addAction(physics_action)
        engine_menu.addSeparator()
        render_menu = engine_menu.addMenu("渲染后端")
        render_group = QActionGroup(self); render_group.setExclusive(True)
        for label, backend_name, checked in (
                ("传统 QPainter", "legacy", True),
                ("命令缓冲 QPainter", "command", False),
                ("实验性 OpenGL", "opengl", False)):
            action = QAction(label, self); action.setCheckable(True); action.setChecked(checked)
            action.triggered.connect(lambda enabled, name=backend_name:
                                     enabled and self.set_render_backend(name))
            render_group.addAction(action); render_menu.addAction(action)
        self.render_backend_group = render_group
        pipeline_action = QAction("打开渲染管线实验室", self)
        pipeline_action.triggered.connect(self.show_pipeline_panel)
        engine_menu.addAction(pipeline_action)
        performance_action = QAction("打开性能分析", self)
        performance_action.triggered.connect(self.show_performance_panel)
        engine_menu.addAction(performance_action)
        instancing_action = QAction("打开纹理/实例化实验", self)
        instancing_action.triggered.connect(self.show_instancing_panel)
        engine_menu.addAction(instancing_action)
        lighting_action = QAction("打开 2D 光照/阴影实验", self)
        lighting_action.triggered.connect(self.show_lighting_panel)
        pipeline3d_action = QAction("打开 3D 渲染管线实验", self)
        pipeline3d_action.triggered.connect(self.show_pipeline3d_panel)
        engine_menu.addAction(pipeline3d_action)
        engine_menu.addAction(lighting_action)
        engine_menu.addSeparator()
        add_spring = QAction("为两个选中图元添加弹簧", self)
        add_spring.triggered.connect(self.add_spring)
        engine_menu.addAction(add_spring)
        toggle_lock = QAction("锁定/解锁当前图层", self)
        toggle_lock.triggered.connect(lambda: self.layer_panel.toggle_current_lock())
        engine_menu.addAction(toggle_lock)
        engine_menu.addSeparator()
        for label, direction in (("选中图元上移一层", 1), ("选中图元下移一层", -1)):
            action = QAction(label, self)
            action.triggered.connect(lambda checked=False, d=direction: self.canvas.adjust_z_order(self.canvas.get_selected_shapes(), d))
            engine_menu.addAction(action)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")

        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def create_toolbar(self) -> None:
        """创建顶部工具栏"""
        # ── 流程图元（下拉菜单）──
        flow_btn = QToolButton()
        flow_btn.setText("流程图元")
        flow_btn.setPopupMode(QToolButton.InstantPopup)
        flow_menu = QMenu()
        for name, tid in [("菱形", "diamond"), ("圆角矩形", "rounded_rect"), ("平行四边形", "parallelogram")]:
            a = flow_menu.addAction(name)
            a.triggered.connect(lambda checked, t=tid: self.graphics_view.set_tool(t))
        flow_btn.setMenu(flow_menu)

        # ── 电路图元（下拉菜单）──
        circuit_btn = QToolButton()
        circuit_btn.setText("电路图元")
        circuit_btn.setPopupMode(QToolButton.InstantPopup)
        circuit_menu = QMenu()
        for name, tid in [("电阻", "resistor"), ("电容", "capacitor"), ("电感", "inductor"),
                           ("接地", "ground"), ("电池", "battery"), ("二极管", "diode"),
                           ("组织节点", "org_node")]:
            a = circuit_menu.addAction(name)
            a.triggered.connect(lambda checked, t=tid: self.graphics_view.set_tool(t))
        circuit_btn.setMenu(circuit_menu)

        # ── 排列工具栏 ──
        arrange_toolbar = QToolBar("排列")
        arrange_toolbar.setIconSize(QSize(32, 32))
        arrange_toolbar.addWidget(flow_btn)
        arrange_toolbar.addWidget(circuit_btn)
        arrange_toolbar.addSeparator()
        for name, handler in [("左对齐", self.align_left), ("居中(H)", self.align_center_h), ("右对齐", self.align_right)]:
            a = QAction(name, self); a.triggered.connect(handler); arrange_toolbar.addAction(a)
        arrange_toolbar.addSeparator()
        for name, handler in [("顶对齐", self.align_top), ("居中(V)", self.align_center_v)]:
            a = QAction(name, self); a.triggered.connect(handler); arrange_toolbar.addAction(a)
        self.addToolBar(arrange_toolbar)

        # ── 编辑工具栏（左侧展开）──
        edit_toolbar = QToolBar("编辑")
        edit_toolbar.setIconSize(QSize(32, 32))
        self.addToolBar(Qt.LeftToolBarArea, edit_toolbar)

        # 菜单与工具栏必须共享同一组 QAction。重复注册相同快捷键会被 Qt
        # 判定为 ambiguous shortcut，导致 Ctrl+Z/Ctrl+Y 不触发任何命令。
        for action in [self.undo_action, self.redo_action, self.cut_action,
                       self.copy_action, self.paste_action, self.delete_action]:
            edit_toolbar.addAction(action)

        # ── 视图工具栏（左侧展开）──
        view_toolbar = QToolBar("视图")
        view_toolbar.setIconSize(QSize(32, 32))
        self.addToolBar(Qt.LeftToolBarArea, view_toolbar)

        for name, handler, shortcut in [
            ("放大", self.zoom_in, QKeySequence.ZoomIn), ("缩小", self.zoom_out, QKeySequence.ZoomOut),
            ("适应窗口", self.fit_to_window, "F"),
        ]:
            a = QAction(name, self); a.setShortcut(shortcut); a.triggered.connect(handler)
            view_toolbar.addAction(a)

    def create_properties_panel(self) -> None:
        """创建属性面板"""
        self.properties_dock = QDockWidget("属性", self)
        self.properties_dock.setObjectName("properties_dock")
        self.properties_dock.setAllowedAreas(Qt.RightDockWidgetArea)
        self.properties_dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        )

        self.properties_panel = PropertiesPanel(self.canvas)
        properties_scroll = QScrollArea()
        properties_scroll.setObjectName("properties_scroll")
        properties_scroll.setWidgetResizable(True)
        properties_scroll.setFrameShape(QFrame.NoFrame)
        properties_scroll.setMinimumSize(300, 0)
        properties_scroll.setWidget(self.properties_panel)
        self.properties_dock.setWidget(properties_scroll)

        self.addDockWidget(Qt.RightDockWidgetArea, self.properties_dock)

        self.layers_dock = QDockWidget("图层", self)
        self.layers_dock.setObjectName("layers_dock")
        self.layer_panel = LayerPanel(self.canvas)
        layers_scroll = QScrollArea()
        layers_scroll.setObjectName("layers_scroll")
        layers_scroll.setWidgetResizable(True)
        layers_scroll.setFrameShape(QFrame.NoFrame)
        layers_scroll.setMinimumSize(300, 0)
        layers_scroll.setWidget(self.layer_panel)
        self.layers_dock.setWidget(layers_scroll)
        self.addDockWidget(Qt.RightDockWidgetArea, self.layers_dock)

        self.inspector_docks = (self.properties_dock, self.layers_dock)
        allowed_areas = Qt.RightDockWidgetArea
        dock_features = (QDockWidget.DockWidgetClosable |
                         QDockWidget.DockWidgetMovable |
                         QDockWidget.DockWidgetFloatable)
        for dock in self.inspector_docks:
            dock.setAllowedAreas(allowed_areas)
            dock.setFeatures(dock_features)
            dock.setMinimumWidth(300)

        # 同一侧栏使用标签页而不是纵向堆叠，避免小窗口下内容被压缩到可视区外。
        self.setTabPosition(Qt.RightDockWidgetArea, QTabWidget.North)
        self.tabifyDockWidget(self.properties_dock, self.layers_dock)
        self.properties_dock.raise_()

        self.view_menu.addSeparator()
        for dock in self.inspector_docks:
            action = dock.toggleViewAction()
            action.triggered.connect(
                lambda checked, target=dock: QTimer.singleShot(0, target.raise_)
                if checked else None)
            self.view_menu.addAction(action)
        self.engine_lab_window = EngineLabWindow(
            self.canvas, self.graphics_view, self)
        # Compatibility accessors: panel ownership now belongs to the lab window.
        self.pipeline_panel = self.engine_lab_window.pipeline_panel
        self.performance_panel = self.engine_lab_window.performance_panel
        self.instancing_panel = self.engine_lab_window.instancing_panel
        self.lighting_panel = self.engine_lab_window.lighting_panel
        self.pipeline3d_panel = self.engine_lab_window.pipeline3d_panel

    def setup_connections(self) -> None:
        """设置信号连接"""
        # 连接画布信号
        self.canvas.canvas_changed.connect(self.on_canvas_changed)
        self.canvas.selection_changed.connect(self.on_selection_changed)
        self.canvas.history_changed.connect(self.on_history_changed)

        # 连接视图信号
        self.graphics_view.viewport_changed.connect(self.on_viewport_changed)
        self.graphics_view.zoom_changed.connect(self.on_zoom_changed)
        self.graphics_view.render_backend_status_changed.connect(self.status_bar.showMessage)
        self.on_history_changed()

    def on_canvas_changed(self) -> None:
        """画布变化时的处理"""
        collision = self.canvas.collision_system
        self.status_bar.showMessage(
            f"图形数量: {len(self.canvas.get_shapes())} | 碰撞对: {len(collision.pairs)} "
            f"| 窄相检测: {collision.last_narrow_phase_tests}"
        )

    def set_engine_debug(self, enabled):
        self.canvas.show_engine_debug = enabled
        self.canvas.canvas_changed.emit()

    def show_pipeline_panel(self):
        self.engine_lab_window.show_page("pipeline")

    def show_performance_panel(self):
        self.engine_lab_window.show_page("performance")

    def show_instancing_panel(self):
        self.engine_lab_window.show_page("instancing")

    def show_lighting_panel(self):
        self.engine_lab_window.show_page("lighting")

    def show_pipeline3d_panel(self):
        self.engine_lab_window.show_page("pipeline3d")

    def set_command_rendering(self, enabled):
        self.graphics_view.set_command_rendering(enabled)
        backend_name = "命令缓冲 QPainter" if enabled else "传统 QPainter"
        self.status_bar.showMessage(f"渲染后端已切换为：{backend_name}")

    def set_render_backend(self, backend_name):
        self.graphics_view.set_render_backend(backend_name)
        labels = {"legacy": "传统 QPainter", "command": "命令缓冲 QPainter",
                  "opengl": "实验性 OpenGL"}
        self.status_bar.showMessage(f"渲染后端已切换为：{labels[backend_name]}")
        QTimer.singleShot(500, self.update_render_backend_status)

    def update_render_backend_status(self):
        self.status_bar.showMessage(self.graphics_view.render_backend_status())

    def closeEvent(self, event):
        if hasattr(self, "engine_lab_window"):
            self.engine_lab_window.hide()
        super().closeEvent(event)

    def add_spring(self):
        selected = self.canvas.get_selected_shapes()
        if len(selected) != 2:
            self.status_bar.showMessage("请选择两个图元后添加弹簧")
            return
        from core.physics import SpringConstraint
        first, second = selected
        distance = (first.bounding_rect().center() - second.bounding_rect().center()).manhattanLength()
        self.canvas.physics_world.springs.append(SpringConstraint(first.id, second.id, max(20, distance)))
        for shape in selected: shape.rigid_body.enabled = True
        self.canvas.canvas_changed.emit()

    def on_selection_changed(self) -> None:
        """选择变化时的处理"""
        selected_count = len(self.canvas.get_selected_shapes())
        if selected_count > 0:
            self.status_bar.showMessage(f"已选择 {selected_count} 个图形")
        else:
            self.status_bar.showMessage("就绪")

    def on_history_changed(self) -> None:
        """历史变化时的处理"""
        self.undo_action.setEnabled(self.canvas.can_undo())
        self.redo_action.setEnabled(self.canvas.can_redo())

    def on_viewport_changed(self) -> None:
        """视口变化时的处理"""
        # 可以在这里更新缩放信息等
        pass

    def on_zoom_changed(self, zoom: float) -> None:
        """缩放变化时的处理"""
        self.status_bar.showMessage(f"缩放: {int(zoom * 100)}%")

    def eventFilter(self, obj, event):
        """事件过滤器"""
        # 只处理需要过滤的事件，其余的让系统处理
        if obj == self.central_widget and event.type() == event.MouseButtonPress:
            # 这里可以添加对中央部件的特殊处理
            pass
        return super().eventFilter(obj, event)

    # 文件操作
    def new_file(self) -> None:
        """新建文件"""
        reply = QMessageBox.question(
            self,
            "新建",
            "是否保存当前文件？",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        )

        if reply == QMessageBox.Save:
            self.save_file()
        elif reply == QMessageBox.Discard:
            self.canvas.clear_canvas()
            self.status_bar.showMessage("新建文件")

    def open_file(self) -> None:
        """打开文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "打开文件", "", "矢量图形文件 (*.json);;所有文件 (*.*)"
        )
        if file_path:
            if self.canvas.load_from_file(file_path):
                self.status_bar.showMessage(f"已打开: {file_path}")
            else:
                QMessageBox.warning(self, "打开失败", "无法打开文件")

    def save_file(self) -> None:
        """保存文件"""
        file_path = getattr(self, "current_file", None)
        if not file_path:
            self.save_file_as()
        else:
            if self.canvas.save_to_file(file_path):
                self.status_bar.showMessage(f"已保存: {file_path}")

    def save_file_as(self) -> None:
        """另存为"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存文件", "untitled.json", "矢量图形文件 (*.json);;所有文件 (*.*)"
        )
        if file_path:
            if not file_path.endswith(".json"):
                file_path += ".json"
            if self.canvas.save_to_file(file_path):
                self.current_file = file_path
                self.status_bar.showMessage(f"已保存: {file_path}")

    def export_svg(self) -> None:
        """导出SVG"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出SVG", "export.svg", "SVG文件 (*.svg);;所有文件 (*.*)"
        )
        if file_path:
            if not file_path.endswith(".svg"):
                file_path += ".svg"
            if self.canvas.export_to_svg(file_path):
                self.status_bar.showMessage(f"已导出: {file_path}")

    def export_png(self) -> None:
        """导出PNG"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出PNG", "export.png", "PNG图片 (*.png);;所有文件 (*.*)"
        )
        if file_path:
            if not file_path.endswith(".png"):
                file_path += ".png"
            if self.canvas.export_to_png(file_path):
                self.status_bar.showMessage(f"已导出: {file_path}")

    # 编辑操作
    def undo(self) -> None:
        """撤销"""
        if self.canvas.undo():
            self.status_bar.showMessage("已撤销")

    def redo(self) -> None:
        """重做"""
        if self.canvas.redo():
            self.status_bar.showMessage("已重做")

    def cut(self) -> None:
        """剪切"""
        selected = self.canvas.get_selected_shapes()
        if selected:
            self.copy()
            self.canvas.delete_selected_shapes()

    def copy(self) -> None:
        """复制 — 将选中图形的数据存入内部剪贴板"""
        selected = self.canvas.get_selected_shapes()
        if selected:
            self._clipboard = [s.to_dict() for s in selected]
            self.status_bar.showMessage(f"已复制 {len(selected)} 个图形")

    def paste(self) -> None:
        """粘贴 — 从内部剪贴板恢复图形"""
        if not self._clipboard:
            self.status_bar.showMessage("剪贴板为空")
            return

        from core.shape import Shape
        pasted = []
        for data in self._clipboard:
            shape = Shape.from_dict(data, preserve_id=False)
            if shape:
                shape.translate(20, 20)  # 偏移以区分原图形
                pasted.append(shape)

        if pasted:
            self.canvas.paste_shapes(pasted)
            self.status_bar.showMessage(f"已粘贴 {len(pasted)} 个图形")

    def delete(self) -> None:
        """删除"""
        self.canvas.delete_selected_shapes()

    # 视图操作
    def zoom_in(self) -> None:
        """放大"""
        self.graphics_view.zoom_in()

    def zoom_out(self) -> None:
        """缩小"""
        self.graphics_view.zoom_out()

    def reset_zoom(self) -> None:
        """重置缩放"""
        self.graphics_view.reset_zoom()

    def fit_to_window(self) -> None:
        """适应窗口"""
        self.graphics_view.fit_to_window()

    def toggle_grid(self) -> None:
        """切换网格显示"""
        self.canvas.set_show_grid(not self.canvas.show_grid)

    def toggle_snap(self) -> None:
        """切换吸附"""
        self.canvas.set_snap_to_grid(not self.canvas.snap_to_grid)

    # ── 对齐与分布 ──

    def _get_arrange_targets(self, min_count, msg):
        shapes = self.canvas.get_selected_shapes()
        if len(shapes) < min_count:
            self.status_bar.showMessage(msg)
            return None
        return shapes

    def align_left(self):
        s = self._get_arrange_targets(2, "至少选择两个图形才能对齐")
        if s: self.canvas.align_left(s)

    def align_right(self):
        s = self._get_arrange_targets(2, "至少选择两个图形才能对齐")
        if s: self.canvas.align_right(s)

    def align_top(self):
        s = self._get_arrange_targets(2, "至少选择两个图形才能对齐")
        if s: self.canvas.align_top(s)

    def align_bottom(self):
        s = self._get_arrange_targets(2, "至少选择两个图形才能对齐")
        if s: self.canvas.align_bottom(s)

    def align_center_h(self):
        s = self._get_arrange_targets(2, "至少选择两个图形才能对齐")
        if s: self.canvas.align_center_h(s)

    def align_center_v(self):
        s = self._get_arrange_targets(2, "至少选择两个图形才能对齐")
        if s: self.canvas.align_center_v(s)

    def distribute_h(self):
        s = self._get_arrange_targets(2, "至少选择两个图形才能分布")
        if s: self.canvas.distribute_h(s)

    def distribute_v(self):
        s = self._get_arrange_targets(2, "至少选择两个图形才能分布")
        if s: self.canvas.distribute_v(s)

    # 帮助
    def show_about(self) -> None:
        """显示关于对话框"""
        QMessageBox.about(
            self,
            "关于",
            "矢量图形编辑器\n\n"
            "版本 1.0.0\n"
            "基于 PyQt5 开发的矢量图形编辑器\n\n"
            "作者：yf y",
        )
