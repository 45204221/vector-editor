"""Dock panel for inspecting the editor's real rendering pipeline."""

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox,
    QPushButton, QScrollArea, QFrame, QTableWidget, QTableWidgetItem,
    QTabWidget, QTextEdit,
    QVBoxLayout, QWidget,
)

from core.pipeline_debug import PipelineDebugMode
from core.raster_experiments import BLEND_MODES, CLIP_MODES, SHADER_MODES
from core.offscreen_experiments import (ATTACHMENT_VIEWS, OFFSCREEN_SCALES,
                                        PICKING_MODES, POSTPROCESS_MODES)


MODE_LABELS = (
    ("最终画面", PipelineDebugMode.FINAL.value),
    ("GPU 三角形线框", PipelineDebugMode.WIREFRAME.value),
    ("Primitive 着色", PipelineDebugMode.PRIMITIVE.value),
    ("批次着色", PipelineDebugMode.BATCH.value),
    ("裁剪区域", PipelineDebugMode.CLIP.value),
    ("Overdraw 热力", PipelineDebugMode.OVERDRAW.value),
)


def _read_only_table(columns, headers):
    table = QTableWidget(0, columns)
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.NoSelection)
    table.verticalHeader().setVisible(False)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    return table


class PipelinePanel(QWidget):
    """Read-only presentation of PipelineSnapshot values."""

    def __init__(self, graphics_view, parent=None):
        super().__init__(parent)
        self.graphics_view = graphics_view
        self.last_snapshot = None
        self._build_ui()
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        graphics_view.pipeline_snapshot_changed.connect(self._refresh_if_visible)
        graphics_view.raster_experiment_changed.connect(self._refresh_if_visible)
        graphics_view.offscreen_experiment_changed.connect(self._refresh_if_visible)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("调试视图"))
        self.mode_combo = QComboBox()
        for label, value in MODE_LABELS:
            self.mode_combo.addItem(label, value)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        controls.addWidget(self.mode_combo, 1)
        refresh_button = QPushButton("刷新")
        refresh_button.clicked.connect(self.refresh)
        controls.addWidget(refresh_button)
        layout.addLayout(controls)

        self.summary_label = QLabel("等待渲染管线数据")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setUsesScrollButtons(True)
        self.tabs.tabBar().setElideMode(Qt.ElideRight)
        layout.addWidget(self.tabs, 1)

        stages_page = QWidget()
        stages_layout = QVBoxLayout(stages_page)
        self.stage_table = _read_only_table(2, ["管线阶段", "真实数据/状态"])
        self.stage_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.stage_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        stages_layout.addWidget(self.stage_table)
        self.tabs.addTab(stages_page, "阶段")

        trace_page = QWidget()
        trace_layout = QVBoxLayout(trace_page)
        self.matrix_label = QLabel("Model matrix：请选择一个图元")
        self.matrix_label.setWordWrap(True)
        trace_layout.addWidget(self.matrix_label)
        self.primitive_table = _read_only_table(
            6, ["#", "拓扑", "Pass", "源顶点", "GPU 顶点", "World bounds"])
        self.primitive_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for column in (0, 2, 3, 4):
            self.primitive_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeToContents)
        self.primitive_table.setMaximumHeight(150)
        trace_layout.addWidget(self.primitive_table)
        self.vertex_table = _read_only_table(
            11, ["P", "V", "Local", "World", "Device/Screen", "Clip x", "Clip y",
                 "Clip w", "NDC x", "NDC y", "Coverage"])
        self.vertex_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        trace_layout.addWidget(self.vertex_table, 1)
        self.tabs.addTab(trace_page, "选中追踪")

        state_page = QWidget()
        state_layout = QVBoxLayout(state_page)
        self.state_table = _read_only_table(2, ["状态", "值"])
        self.state_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.state_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        state_layout.addWidget(self.state_table)
        self.shader_text = QTextEdit()
        self.shader_text.setReadOnly(True)
        self.shader_text.setMaximumHeight(115)
        state_layout.addWidget(self.shader_text)
        self.tabs.addTab(state_page, "GPU 状态")

        experiment_page = QWidget()
        experiment_layout = QVBoxLayout(experiment_page)
        experiment_form = QFormLayout()
        self.shader_combo = self._experiment_combo(SHADER_MODES)
        self.blend_combo = self._experiment_combo(BLEND_MODES)
        self.clip_combo = self._experiment_combo(CLIP_MODES)
        experiment_form.addRow("Shader 变体", self.shader_combo)
        experiment_form.addRow("混合状态", self.blend_combo)
        experiment_form.addRow("光栅裁剪", self.clip_combo)
        experiment_layout.addLayout(experiment_form)
        reset_button = QPushButton("恢复实验默认值")
        reset_button.clicked.connect(self.graphics_view.reset_raster_experiment)
        experiment_layout.addWidget(reset_button)
        self.experiment_state_label = QLabel()
        self.experiment_state_label.setWordWrap(True)
        self.experiment_state_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        experiment_layout.addWidget(self.experiment_state_label)
        experiment_help = QLabel(
            "实验只作用于 OpenGL 矢量三角形 pass；文字、选择框与调试覆盖层保留 Qt 绘制，"
            "便于比较 GPU pass 和编辑器 overlay pass。")
        experiment_help.setWordWrap(True)
        experiment_help.setMaximumHeight(64)
        experiment_help.setToolTip(experiment_help.text())
        experiment_layout.addWidget(experiment_help)
        experiment_layout.addStretch(1)
        self.tabs.addTab(self._scroll_page(experiment_page, "shader_experiment_scroll"),
                         "Shader 实验")

        offscreen_page = QWidget()
        offscreen_layout = QVBoxLayout(offscreen_page)
        pick_form = QFormLayout()
        self.picking_combo = self._experiment_combo(PICKING_MODES, self._picking_changed)
        pick_form.addRow("选择路径", self.picking_combo)
        self.attachment_combo = self._experiment_combo(
            ATTACHMENT_VIEWS, self._offscreen_config_changed)
        self.postprocess_combo = self._experiment_combo(
            POSTPROCESS_MODES, self._offscreen_config_changed)
        self.offscreen_scale_combo = self._experiment_combo(
            OFFSCREEN_SCALES, self._offscreen_config_changed)
        pick_form.addRow("查看附件", self.attachment_combo)
        pick_form.addRow("后处理", self.postprocess_combo)
        pick_form.addRow("离屏分辨率", self.offscreen_scale_combo)
        offscreen_layout.addLayout(pick_form)
        self.offscreen_state_label = QLabel()
        self.offscreen_state_label.setWordWrap(True)
        self.offscreen_state_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        offscreen_layout.addWidget(self.offscreen_state_label)
        attachment_controls = QHBoxLayout()
        attachment_button = QPushButton("生成附件预览")
        attachment_button.clicked.connect(self._render_attachment_preview)
        attachment_controls.addWidget(attachment_button)
        export_button = QPushButton("导出当前附件 PNG")
        export_button.clicked.connect(self._export_attachment)
        attachment_controls.addWidget(export_button)
        offscreen_layout.addLayout(attachment_controls)
        self.id_attachment_label = QLabel(
            "CPU 默认模式不创建 ID FBO；请选择“对照”或“GPU 实验”。")
        self.id_attachment_label.setAlignment(Qt.AlignCenter)
        self.id_attachment_label.setMinimumHeight(150)
        self.id_attachment_label.setStyleSheet(
            "QLabel { background: #20242a; color: #c9d1d9; border: 1px solid #555; }")
        offscreen_layout.addWidget(self.id_attachment_label, 1)
        pick_note = QLabel(
            "对照模式仍以 CPU 结果选择；GPU 实验失败时自动回退。ID 预览是手动读回，"
            "避免面板定时刷新持续造成 GPU→CPU 同步。Qt 文字在本阶段不进入 GPU ID pass，"
            "点击文字时可用对照模式观察两条路径的差异。颜色/后处理导出只包含 GPU "
            "vector pass，不含网格、文字、选择框和调试覆盖层。")
        pick_note.setWordWrap(True)
        pick_note.setMaximumHeight(84)
        pick_note.setToolTip(pick_note.text())
        offscreen_layout.addWidget(pick_note)
        self.tabs.addTab(self._scroll_page(offscreen_page, "offscreen_experiment_scroll"),
                         "离屏/拾取")

        self.note_label = QLabel("调试数据只读，不进入文档、保存或撤销历史")
        self.note_label.setWordWrap(True)
        layout.addWidget(self.note_label)

    @staticmethod
    def _scroll_page(widget, object_name):
        scroll = QScrollArea()
        scroll.setObjectName(object_name)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(widget)
        return scroll

    def _experiment_combo(self, choices, callback=None):
        combo = QComboBox()
        for label, value in choices:
            combo.addItem(label, value)
        combo.currentIndexChanged.connect(callback or self._experiment_changed)
        return combo

    def _experiment_changed(self):
        if not hasattr(self, "clip_combo"):
            return
        self.graphics_view.set_raster_experiment(
            self.shader_combo.currentData(), self.blend_combo.currentData(),
            self.clip_combo.currentData())

    def _picking_changed(self):
        self.graphics_view.set_picking_mode(self.picking_combo.currentData())

    def _offscreen_config_changed(self):
        if not hasattr(self, "offscreen_scale_combo"):
            return
        self.graphics_view.set_offscreen_preview_config(
            self.postprocess_combo.currentData(), self.attachment_combo.currentData(),
            self.offscreen_scale_combo.currentData())
        self.last_offscreen_image = None

    def _render_attachment_preview(self):
        image = self.graphics_view.render_offscreen_attachment()
        if image is None or image.isNull():
            self.id_attachment_label.setPixmap(QPixmap())
            state = self.graphics_view.offscreen_experiment_state()
            self.id_attachment_label.setText(
                state.get("offscreen_error") or state.get("warning") or
                "附件尚不可用；请启用 OpenGL 并等待一帧。")
            return
        self.last_offscreen_image = image
        pixmap = QPixmap.fromImage(image).scaled(
            self.id_attachment_label.size(), Qt.KeepAspectRatio,
            Qt.FastTransformation)
        self.id_attachment_label.setText("")
        self.id_attachment_label.setPixmap(pixmap)
        self.refresh()

    def _export_attachment(self):
        image = getattr(self, "last_offscreen_image", None)
        if image is None or image.isNull():
            image = self.graphics_view.render_offscreen_attachment()
        if image is None or image.isNull():
            self._render_attachment_preview()
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出离屏附件", "offscreen_output.png", "PNG 图像 (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        if not image.save(path, "PNG"):
            QMessageBox.warning(self, "导出失败", "无法写入所选 PNG 文件。")

    @staticmethod
    def _select_data(combo, value):
        index = combo.findData(value)
        if index < 0 or index == combo.currentIndex():
            return
        combo.blockSignals(True)
        combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _refresh_experiment(self):
        state = self.graphics_view.raster_experiment_state()
        self._select_data(self.shader_combo, state["shader_mode"])
        self._select_data(self.blend_combo, state["blend_mode"])
        self._select_data(self.clip_combo, state["clip_mode"])
        activity = "OpenGL 中生效" if state["active"] else "当前后端未激活实验"
        warning = f"\n提示：{state['warning']}" if state["warning"] else ""
        self.experiment_state_label.setText(
            f"{activity}\n"
            f"实际裁剪：{state['effective_clip_mode']}\n"
            f"Stencil bits：{state['stencil_bits']}\n"
            f"u_time：{state['time_uniform']:.3f}{warning}")

    def _refresh_offscreen(self):
        state = self.graphics_view.offscreen_experiment_state()
        self._select_data(self.picking_combo, state["picking_mode"])
        self._select_data(self.postprocess_combo, self.graphics_view.postprocess_mode)
        self._select_data(self.attachment_combo, self.graphics_view.attachment_view)
        self._select_data(self.offscreen_scale_combo, self.graphics_view.offscreen_scale)
        result = ("一致" if state["matched"] else "不一致")
        warning = f"\n提示：{state['warning']}" if state["warning"] else ""
        self.offscreen_state_label.setText(
            f"FBO：{'有效' if state['target_valid'] else '未创建'} "
            f"{state['target_size']} · revision {state['target_revision']}\n"
            f"附件：{state['attachment']} · 映射 {state['mapped_shapes']} 图元\n"
            f"CPU：{state['cpu_shape_id'] or '背景'} · {state['cpu_ms']:.4f} ms\n"
            f"GPU：{state['gpu_shape_id'] or '背景'} · {state['gpu_ms']:.4f} ms "
            f"· {result}\n"
            f"颜色/后处理 FBO：{state['color_target_size']} · "
            f"{'有效' if state['color_target_valid'] and state['post_target_valid'] else '未生成'}\n"
            f"效果：{state['postprocess_effect']} · {state['offscreen_ms']:.3f} ms · "
            f"约 {state['offscreen_bytes'] / (1024 * 1024):.1f} MiB"
            f"{warning or (chr(10) + '提示：' + state['offscreen_error'] if state['offscreen_error'] else '')}")

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start()
        self.refresh()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def _refresh_if_visible(self):
        if self.isVisible():
            self.refresh()

    def _mode_changed(self):
        mode = self.mode_combo.currentData()
        self.graphics_view.set_pipeline_debug_mode(mode)
        self.note_label.setText(
            "调试数据只读，不进入文档、保存或撤销历史" +
            ("；Overdraw 是三角形透明叠加近似" if mode == "overdraw" else ""))
        self.refresh()

    @staticmethod
    def _point(point):
        return f"({point[0]:.2f}, {point[1]:.2f})"

    @staticmethod
    def _set_rows(table, rows):
        table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(str(value)))

    def refresh(self):
        self._refresh_experiment()
        self._refresh_offscreen()
        try:
            snapshot = self.graphics_view.pipeline_snapshot()
        except Exception as error:
            self.summary_label.setText(f"管线快照暂不可用：{error}")
            return
        self.last_snapshot = snapshot
        self.summary_label.setText(
            f"{snapshot.backend_name} · revision {snapshot.revision} · "
            f"选中 {snapshot.selected_shape_id or '—'}")
        self._set_rows(self.stage_table, snapshot.stages)
        self._set_rows(self.state_table, snapshot.state)

        primitive_rows = []
        vertex_rows = []
        for primitive in snapshot.primitive_traces:
            bounds = tuple(round(value, 2) for value in primitive.world_bounds)
            primitive_rows.append((primitive.primitive_index, primitive.topology,
                                   primitive.render_pass, primitive.source_vertex_count,
                                   primitive.gpu_vertex_count, bounds))
            for vertex_index, vertex in enumerate(primitive.vertices):
                vertex_rows.append((
                    primitive.primitive_index, vertex_index, self._point(vertex.local),
                    self._point(vertex.world), self._point(vertex.device),
                    f"{vertex.clip[0]:.4f}", f"{vertex.clip[1]:.4f}",
                    f"{vertex.clip[3]:.1f}", f"{vertex.ndc[0]:.4f}",
                    f"{vertex.ndc[1]:.4f}", f"{vertex.coverage:.2f}"))
        if snapshot.primitive_traces:
            m11, m12, m21, m22, dx, dy = snapshot.primitive_traces[0].model_matrix
            self.matrix_label.setText(
                "Model matrix\n"
                f"[{m11:.3f}  {m21:.3f}  {dx:.3f}]\n"
                f"[{m12:.3f}  {m22:.3f}  {dy:.3f}]\n"
                "[0.000  0.000  1.000]")
        else:
            self.matrix_label.setText("Model matrix：请选择一个图元")
        self._set_rows(self.primitive_table, primitive_rows)
        self._set_rows(self.vertex_table, vertex_rows)
        if not primitive_rows:
            self.primitive_table.setRowCount(1)
            self.primitive_table.setItem(0, 1, QTableWidgetItem("请选择一个图元"))

        self.shader_text.setPlainText(
            f"顶点布局\n{snapshot.vertex_layout}\n\nShader / Raster / Blend\n"
            f"{snapshot.shader_summary}\n\n{snapshot.overdraw_note}")
