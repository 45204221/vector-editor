"""Controls and observability for the texture-atlas instancing experiment."""

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox,
                             QHBoxLayout, QLabel, QPushButton, QSpinBox,
                             QVBoxLayout, QWidget)

from core.instancing_experiment import (MAX_INSTANCES, SPRITE_MODES,
                                        build_sprite_atlas)


class InstancingPanel(QWidget):
    def __init__(self, graphics_view, parent=None):
        super().__init__(parent)
        self.graphics_view = graphics_view
        self._build_ui()
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        graphics_view.instancing_experiment_changed.connect(self.refresh)
        graphics_view.gpu_text_experiment_changed.connect(self.refresh)
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        intro = QLabel(
            "一个 Quad + 一个 Atlas + 一份 per-instance buffer，通过一次 "
            "glDrawArraysInstanced 绘制全部精灵。")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        controls_group = QGroupBox("实例化控制")
        form = QFormLayout(controls_group)
        self.enabled_check = QCheckBox("在主 OpenGL 画布显示")
        self.animate_check = QCheckBox("GPU uniform 动画")
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, MAX_INSTANCES)
        self.count_spin.setSingleStep(100)
        self.sprite_combo = QComboBox()
        for label, value in SPRITE_MODES:
            self.sprite_combo.addItem(label, value)
        form.addRow(self.enabled_check)
        form.addRow("实例数量", self.count_spin)
        form.addRow("Atlas Cell", self.sprite_combo)
        form.addRow(self.animate_check)
        reset_button = QPushButton("重新生成确定性实例")
        reset_button.clicked.connect(self.graphics_view.reset_instancing_seed)
        form.addRow(reset_button)
        layout.addWidget(controls_group)

        atlas_group = QGroupBox("程序化纹理图集（3 × 64 px）")
        atlas_layout = QVBoxLayout(atlas_group)
        self.atlas_label = QLabel()
        self.atlas_label.setAlignment(Qt.AlignCenter)
        self.atlas_label.setStyleSheet(
            "QLabel { background: #20242a; border: 1px solid #555; }")
        self.atlas_label.setPixmap(QPixmap.fromImage(build_sprite_atlas()).scaled(
            576, 192, Qt.KeepAspectRatio, Qt.FastTransformation))
        atlas_layout.addWidget(self.atlas_label)
        atlas_caption = QLabel("UV: 圆形 [0,⅓] · 菱形 [⅓,⅔] · 星形 [⅔,1]")
        atlas_caption.setAlignment(Qt.AlignCenter)
        atlas_layout.addWidget(atlas_caption)
        layout.addWidget(atlas_group)

        text_group = QGroupBox("动态字形 Atlas / GPU 文字")
        text_layout = QVBoxLayout(text_group)
        self.gpu_text_check = QCheckBox("使用 GPU 字形 Atlas 绘制文字图元")
        self.gpu_text_check.toggled.connect(
            self.graphics_view.set_gpu_text_experiment)
        text_layout.addWidget(self.gpu_text_check)
        self.gpu_text_demo_check = QCheckBox("在画布显示运行时 GPU 文字示例")
        self.gpu_text_demo_check.toggled.connect(
            lambda checked: self.graphics_view.set_gpu_text_experiment(
                show_demo=checked))
        text_layout.addWidget(self.gpu_text_demo_check)
        text_help = QLabel(
            "Qt 负责字体度量与字形栅格化；OpenGL 从共享 1024×1024 Atlas "
            "采样。关闭后可与原 QPainter 文字路径直接对照。")
        text_help.setWordWrap(True)
        text_layout.addWidget(text_help)
        self.gpu_text_state_label = QLabel()
        self.gpu_text_state_label.setWordWrap(True)
        self.gpu_text_state_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text_layout.addWidget(self.gpu_text_state_label)
        layout.addWidget(text_group)

        self.state_label = QLabel()
        self.state_label.setWordWrap(True)
        self.state_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.state_label)
        note = QLabel(
            "实验覆盖层不进入文档、图层、碰撞、拾取或离屏导出。配置不变时动画只更新 "
            "u_time，不重复上传实例数据。")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

        self.enabled_check.toggled.connect(self._controls_changed)
        self.animate_check.toggled.connect(self._controls_changed)
        self.count_spin.valueChanged.connect(self._controls_changed)
        self.sprite_combo.currentIndexChanged.connect(self._controls_changed)

    def _controls_changed(self):
        self.graphics_view.set_instancing_experiment(
            enabled=self.enabled_check.isChecked(),
            count=self.count_spin.value(),
            sprite_mode=self.sprite_combo.currentData(),
            animate=self.animate_check.isChecked())

    def refresh(self):
        state = self.graphics_view.instancing_experiment_state()
        text_state = self.graphics_view.gpu_text_experiment_state()
        controls = (self.enabled_check, self.animate_check,
                    self.count_spin, self.sprite_combo, self.gpu_text_check,
                    self.gpu_text_demo_check)
        for control in controls:
            control.blockSignals(True)
        self.enabled_check.setChecked(state["enabled"])
        self.animate_check.setChecked(state["animate"])
        self.count_spin.setValue(state["count"])
        index = self.sprite_combo.findData(state["sprite_mode"])
        if index >= 0:
            self.sprite_combo.setCurrentIndex(index)
        self.gpu_text_check.setChecked(text_state["enabled"])
        self.gpu_text_demo_check.setChecked(text_state["show_demo"])
        for control in controls:
            control.blockSignals(False)
        error = f"\n提示：{state['error']}" if state["error"] else ""
        self.state_label.setText(
            f"资源：{'有效' if state['resources_valid'] else '未创建'} · "
            f"Atlas {state['atlas_size']}\n"
            f"实例：{state['count']} · {state['instance_bytes']} bytes · "
            f"上传 {state['upload_count']} 次\n"
            f"Draw calls：{state['draw_calls']} · u_time {state['time_uniform']:.3f}"
            f"{error}")
        text_error = f"\n提示：{text_state['error']}" if text_state["error"] else ""
        self.gpu_text_state_label.setText(
            f"资源：{'有效' if text_state['resources_valid'] else '未创建'} · "
            f"Atlas {text_state['atlas_size']} / {text_state['atlas_bytes']} bytes\n"
            f"唯一字形 {text_state['unique_glyphs']} · 可见字形 "
            f"{text_state['rendered_glyphs']} · 顶点 {text_state['vertices']} · "
            f"VBO {text_state['vbo_bytes']} bytes\n"
            f"Draw calls {text_state['draw_calls']} · 上传 {text_state['upload_count']} · "
            f"Atlas 重建 {text_state['atlas_rebuild_count']} · "
            f"Qt 回退命令 {text_state['fallback_commands']} · "
            f"运行时示例 {'开启' if text_state['show_demo'] else '关闭'}{text_error}")

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start()
        self.refresh()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)
