"""Controls and algorithm observability for M16 2D visibility/lighting."""

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                             QGroupBox, QHBoxLayout, QLabel, QPushButton,
                             QVBoxLayout, QWidget)

from core.lighting_experiment import DEBUG_MODES


class LightingPanel(QWidget):
    def __init__(self, graphics_view, parent=None):
        super().__init__(parent)
        self.graphics_view = graphics_view
        self._build_ui()
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        graphics_view.lighting_experiment_changed.connect(self.refresh)
        self.refresh()

    def _spin(self, minimum, maximum, decimals=1, step=1.0):
        control = QDoubleSpinBox()
        control.setRange(minimum, maximum)
        control.setDecimals(decimals)
        control.setSingleStep(step)
        return control

    def _build_ui(self):
        layout = QVBoxLayout(self)
        intro = QLabel(
            "C++ 对遮挡端点发射 angle±epsilon 射线，使用叉积完成 ray/segment "
            "最近交点测试并生成 visibility polygon；OpenGL 将它作为 triangle fan 写入 "
            "Shadow Mask，再生成径向光照纹理并乘法合成回画布。")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        group = QGroupBox("单光源 / 可见性参数")
        form = QFormLayout(group)
        self.enabled_check = QCheckBox("在主画布显示算法结果")
        self.light_combo = QComboBox()
        light_buttons = QWidget(); light_buttons_layout = QHBoxLayout(light_buttons)
        light_buttons_layout.setContentsMargins(0, 0, 0, 0)
        add_light = QPushButton("新增光源")
        remove_light = QPushButton("删除当前")
        add_light.clicked.connect(self._add_light)
        remove_light.clicked.connect(self._remove_light)
        light_buttons_layout.addWidget(add_light); light_buttons_layout.addWidget(remove_light)
        self.x_spin = self._spin(-10000, 10000)
        self.y_spin = self._spin(-10000, 10000)
        self.radius_spin = self._spin(10, 10000, 1, 10)
        self.intensity_spin = self._spin(0, 4, 2, 0.1)
        self.ambient_spin = self._spin(0, 1, 2, 0.05)
        self.debug_combo = QComboBox()
        for label, value in DEBUG_MODES:
            self.debug_combo.addItem(label, value)
        self.native_check = QCheckBox("优先使用 C++17 kernel")
        self.gpu_check = QCheckBox("启用 OpenGL 单光源合成")
        self.color_combo = QComboBox()
        for label, value in (("暖黄", "#FFD36A"), ("冷蓝", "#68B8FF"),
                             ("红光", "#FF4545"), ("深蓝", "#458CFF"),
                             ("火焰橙", "#FF8A45"), ("白光", "#FFFFFF")):
            self.color_combo.addItem(label, value)
        form.addRow(self.enabled_check)
        form.addRow("当前光源", self.light_combo)
        form.addRow(light_buttons)
        form.addRow("光源 X", self.x_spin)
        form.addRow("光源 Y", self.y_spin)
        form.addRow("光照半径", self.radius_spin)
        form.addRow("光照强度", self.intensity_spin)
        form.addRow("环境光", self.ambient_spin)
        form.addRow("光源颜色", self.color_combo)
        form.addRow("调试视图", self.debug_combo)
        form.addRow(self.native_check)
        form.addRow(self.gpu_check)
        center = QPushButton("将光源放到画布中心")
        center.clicked.connect(self._center_light)
        form.addRow(center)
        layout.addWidget(group)

        help_label = QLabel(
            "也可直接在主画布拖拽黄色光源点。红色虚线是输入 segments，黄色射线是最近命中，"
            "粉色点是交点，半透明区域是排序后的可见多边形。")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        self.state_label = QLabel()
        self.state_label.setWordWrap(True)
        self.state_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.state_label)

        attachment_group = QGroupBox("OpenGL 中间附件（手动读取）")
        attachment_layout = QVBoxLayout(attachment_group)
        self.attachment_combo = QComboBox()
        self.attachment_combo.addItem("Shadow Mask", "mask")
        self.attachment_combo.addItem("Light Texture", "light")
        attachment_layout.addWidget(self.attachment_combo)
        attachment_button = QPushButton("生成附件预览")
        attachment_button.clicked.connect(self._preview_attachment)
        attachment_layout.addWidget(attachment_button)
        self.attachment_preview = QLabel("切换到 OpenGL 并启用光照后生成预览")
        self.attachment_preview.setAlignment(Qt.AlignCenter)
        self.attachment_preview.setMinimumHeight(150)
        self.attachment_preview.setStyleSheet("background:#20252b; color:#d7dde5")
        attachment_layout.addWidget(self.attachment_preview)
        layout.addWidget(attachment_group)
        theory = QLabel(
            "复杂度：V 个端点产生约 3V 条射线，每条与 E 条边求交，朴素实现 O(V·E)。"
            "M16.3 将在真实动态场景中讨论空间索引与 revision 缓存。")
        theory.setWordWrap(True)
        layout.addWidget(theory)
        layout.addStretch(1)

        for control in (self.enabled_check, self.x_spin, self.y_spin,
                        self.radius_spin, self.intensity_spin, self.ambient_spin,
                        self.color_combo, self.debug_combo, self.native_check,
                        self.gpu_check):
            signal = (control.toggled if isinstance(control, QCheckBox)
                      else control.currentIndexChanged if isinstance(control, QComboBox)
                      else control.valueChanged)
            signal.connect(self._controls_changed)
        self.light_combo.currentIndexChanged.connect(self._light_selected)

    def _center_light(self):
        self.graphics_view.set_selected_light_parameters(
            x=self.graphics_view.canvas.width / 2,
            y=self.graphics_view.canvas.height / 2)

    def _add_light(self):
        if not self.graphics_view.add_lighting_source():
            self.state_label.setText("最多支持 8 个运行时光源。")

    def _remove_light(self):
        if not self.graphics_view.remove_selected_lighting_source():
            self.state_label.setText("主光源必须保留；请选择额外光源后删除。")

    def _light_selected(self, index):
        if index >= 0:
            self.graphics_view.select_lighting_source(index)

    def _controls_changed(self):
        self.graphics_view.set_lighting_experiment(
            enabled=self.enabled_check.isChecked(), ambient=self.ambient_spin.value(),
            debug_mode=self.debug_combo.currentData(),
            use_native=self.native_check.isChecked(),
            gpu_lighting=self.gpu_check.isChecked())
        self.graphics_view.set_selected_light_parameters(
            x=self.x_spin.value(), y=self.y_spin.value(),
            radius=self.radius_spin.value(), intensity=self.intensity_spin.value(),
            color=self.color_combo.currentData())

    def _preview_attachment(self):
        image = self.graphics_view.render_lighting_attachment(
            self.attachment_combo.currentData())
        if image is None or image.isNull():
            self.attachment_preview.setText("附件不可用；请确认 OpenGL 后端与 GPU 光照已启用")
            return
        pixmap = QPixmap.fromImage(image).scaled(
            520, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.attachment_preview.setPixmap(pixmap)

    def refresh(self):
        state = self.graphics_view.lighting_experiment_state()
        controls = (self.enabled_check, self.x_spin, self.y_spin,
                    self.radius_spin, self.intensity_spin, self.ambient_spin,
                    self.color_combo, self.debug_combo, self.native_check,
                    self.gpu_check)
        for control in controls:
            control.blockSignals(True)
        self.light_combo.blockSignals(True)
        if self.light_combo.count() != state["light_count"]:
            self.light_combo.clear()
            for index in range(state["light_count"]):
                self.light_combo.addItem(f"L{index + 1}", index)
        self.light_combo.setCurrentIndex(state["selected_light"])
        self.enabled_check.setChecked(state["enabled"])
        self.x_spin.setValue(state["light_x"]); self.y_spin.setValue(state["light_y"])
        self.radius_spin.setValue(state["radius"])
        self.intensity_spin.setValue(state["intensity"])
        self.ambient_spin.setValue(state["ambient"])
        index = self.color_combo.findData(state["color"])
        if index >= 0:
            self.color_combo.setCurrentIndex(index)
        index = self.debug_combo.findData(state["debug_mode"])
        if index >= 0:
            self.debug_combo.setCurrentIndex(index)
        self.native_check.setChecked(state["use_native"])
        self.gpu_check.setChecked(state["gpu_lighting"])
        for control in controls:
            control.blockSignals(False)
        self.light_combo.blockSignals(False)
        messages = [message for message in (state["warning"], state["error"])
                    if message]
        warning = f"\n提示：{'；'.join(messages)}" if messages else ""
        self.state_label.setText(
            f"算法：{state['backend']} · revision {state['revision']} · "
            f"构建 {state['build_ms']:.3f} ms · "
            f"Lights {state['light_count']} · 选中 L{state['selected_light'] + 1}\n"
            f"Segments {state['segments']} · Rays {state['rays']} · "
            f"Polygon {state['polygon_points']} points\n"
            f"Ray/segment tests {state['intersection_tests']} · "
            f"截断 {'是' if state['truncated'] else '否'}\n"
            f"GPU {'生效' if state['gpu_active'] else '未生效'} · "
            f"FBO {state['target_size']} · Fan {state['fan_vertices']} vertices / "
            f"{state['fan_vbo_bytes']} bytes · Upload {state['upload_count']}\n"
            f"Pass draws {state['draw_calls']} · {state['pass_ms']:.3f} ms · "
            f"附件约 {state['fbo_bytes'] / 1048576.0:.2f} MiB\n"
            f"Visibility builds {state['visibility_build_count']} · "
            f"uniform/debug cache hits {state['visibility_cache_hits']}{warning}")

    def showEvent(self, event):
        super().showEvent(event); self.timer.start(); self.refresh()

    def hideEvent(self, event):
        self.timer.stop(); super().hideEvent(event)
