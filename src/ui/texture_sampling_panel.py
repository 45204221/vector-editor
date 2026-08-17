"""M19 texture filtering, mipmap and LOD visualization laboratory."""

import math
import struct
import time

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (QImage, QOpenGLBuffer, QOpenGLShader,
                         QOpenGLShaderProgram, QOpenGLTexture,
                         QOpenGLVertexArrayObject, QOpenGLVersionProfile,
                         QVector2D)
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                             QGroupBox, QHBoxLayout, QLabel, QPushButton,
                             QScrollArea, QSlider, QSplitter, QVBoxLayout,
                             QWidget, QOpenGLWidget)

from core.native_texture import (generate_mipmaps, runtime_error,
                                 sample_texture)
from core.texture_sampling import (build_checker_texture,
                                   generate_mipmaps as python_generate,
                                   sample_mipmaps as python_sample)
from .pipeline3d_panel import _PipelineGLFunctions


GL_COLOR_BUFFER_BIT = 0x00004000
GL_FLOAT = 0x1406
GL_TRIANGLES = 0x0004
GL_TEXTURE_2D = 0x0DE1
GL_TEXTURE_MIN_FILTER = 0x2801
GL_TEXTURE_MAG_FILTER = 0x2800
GL_TEXTURE_BASE_LEVEL = 0x813C
GL_TEXTURE_MAX_LEVEL = 0x813D
GL_NEAREST = 0x2600
GL_LINEAR = 0x2601
GL_LINEAR_MIPMAP_LINEAR = 0x2703

VERTEX_SHADER = """
attribute vec4 a_clip;
attribute vec2 a_uv;
varying vec2 v_uv;
uniform float u_tiling;
uniform float u_phase;
void main() {
    gl_Position = a_clip;
    v_uv = a_uv * u_tiling + vec2(u_phase, 0.0);
}
"""

FRAGMENT_SHADER = """
uniform sampler2D u_texture;
uniform vec2 u_texture_size;
uniform float u_max_lod;
uniform int u_view;
varying vec2 v_uv;

float estimated_lod() {
    vec2 dx = dFdx(v_uv * u_texture_size);
    vec2 dy = dFdy(v_uv * u_texture_size);
    float rho = max(length(dx), length(dy));
    return clamp(log2(max(rho, 0.000001)), 0.0, u_max_lod);
}

vec3 lod_color(float value) {
    float t = value / max(1.0, u_max_lod);
    return clamp(vec3(1.5 * t, 1.5 - abs(2.0 * t - 1.0) * 1.5,
                      1.5 * (1.0 - t)), 0.0, 1.0);
}

void main() {
    vec4 sampled = texture2D(u_texture, v_uv);
    float lod = estimated_lod();
    if (u_view == 1) {
        gl_FragColor = vec4(mix(sampled.rgb, lod_color(floor(lod + 0.5)), 0.68), 1.0);
    } else if (u_view == 2) {
        gl_FragColor = vec4(lod_color(lod), 1.0);
    } else {
        gl_FragColor = sampled;
    }
}
"""


class TextureSamplingViewport(QOpenGLWidget):
    state_changed = pyqtSignal()

    def __init__(self, base_rgba, texture_size, parent=None):
        super().__init__(parent)
        self.base_rgba = bytes(base_rgba)
        self.texture_size = int(texture_size)
        self.filter_mode = "trilinear"
        self.view_mode = "final"
        self.repeat = True
        self.manual_lod = False
        self.lod_level = 0
        self.tiling = 16.0
        self.phase = 0.0
        self.functions = self.program = self.buffer = self.vertex_array = None
        self.texture = None
        self.texture_uploads = self.geometry_uploads = 0
        self.draw_calls = self.frame_count = 0
        self.draw_ms = 0.0
        self.last_error = ""
        self.setMinimumSize(430, 380)

    @property
    def max_lod(self):
        return int(math.floor(math.log2(self.texture_size)))

    def initializeGL(self):
        try:
            context = self.context()
            profile = QOpenGLVersionProfile(context.format())
            self.functions = context.versionFunctions(profile)
            if self.functions is None:
                self.functions = _PipelineGLFunctions(context)
            self.functions.initializeOpenGLFunctions()
            program = QOpenGLShaderProgram()
            if not program.addShaderFromSourceCode(QOpenGLShader.Vertex, VERTEX_SHADER):
                raise RuntimeError(program.log())
            if not program.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAGMENT_SHADER):
                raise RuntimeError(program.log())
            program.bindAttributeLocation("a_clip", 0)
            program.bindAttributeLocation("a_uv", 1)
            if not program.link():
                raise RuntimeError(program.log())
            buffer = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
            vertex_array = QOpenGLVertexArrayObject()
            if not buffer.create() or not vertex_array.create():
                raise RuntimeError("无法创建 texture laboratory VAO/VBO")
            # Clip-space w grows toward the top, producing real perspective UV
            # compression without introducing an unrelated camera system.
            vertices = (
                (-0.95, -0.88, 0.0, 1.0, 0.0, 0.0),
                (0.95, -0.88, 0.0, 1.0, 1.0, 0.0),
                (1.05, 1.65, 0.0, 3.0, 1.0, 1.0),
                (-0.95, -0.88, 0.0, 1.0, 0.0, 0.0),
                (1.05, 1.65, 0.0, 3.0, 1.0, 1.0),
                (-1.05, 1.65, 0.0, 3.0, 0.0, 1.0),
            )
            payload = struct.pack("<{}f".format(len(vertices) * 6),
                                  *(value for vertex in vertices for value in vertex))
            vertex_array.bind(); buffer.bind(); buffer.allocate(payload, len(payload))
            program.bind()
            for name, offset, count in (("a_clip", 0, 4), ("a_uv", 16, 2)):
                location = program.attributeLocation(name)
                program.enableAttributeArray(location)
                program.setAttributeBuffer(location, GL_FLOAT, offset, count, 24)
            program.release(); buffer.release(); vertex_array.release()
            self.geometry_uploads += 1
            image = QImage(self.base_rgba, self.texture_size, self.texture_size,
                           self.texture_size * 4, QImage.Format_RGBA8888).copy()
            texture = QOpenGLTexture(image)
            if not texture.isCreated():
                raise RuntimeError("无法创建 RGBA8 texture")
            texture.generateMipMaps()
            texture.setWrapMode(QOpenGLTexture.Repeat)
            self.texture_uploads += 1
            self.program, self.buffer, self.vertex_array = program, buffer, vertex_array
            self.texture = texture
            self.last_error = ""
        except Exception as error:
            self.last_error = str(error)
        self.state_changed.emit()

    def set_options(self, **options):
        for name, value in options.items():
            setattr(self, name, value)
        self.update()

    def resizeGL(self, width, height):
        if self.functions:
            self.functions.glViewport(0, 0, max(1, width), max(1, height))

    def paintGL(self):
        started = time.perf_counter()
        try:
            if (self.functions is None or self.program is None or
                    self.buffer is None or self.vertex_array is None or
                    self.texture is None):
                return
            self.functions.glViewport(0, 0, max(1, self.width()), max(1, self.height()))
            self.functions.glClearColor(0.055, 0.075, 0.105, 1.0)
            self.functions.glClear(GL_COLOR_BUFFER_BIT)
            self.texture.bind(0)
            minimum = {"nearest": GL_NEAREST, "bilinear": GL_LINEAR,
                       "trilinear": GL_LINEAR_MIPMAP_LINEAR}[self.filter_mode]
            maximum = GL_NEAREST if self.filter_mode == "nearest" else GL_LINEAR
            self.functions.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, minimum)
            self.functions.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, maximum)
            self.functions.glTexParameteri(
                GL_TEXTURE_2D, GL_TEXTURE_BASE_LEVEL,
                self.lod_level if self.manual_lod else 0)
            self.functions.glTexParameteri(
                GL_TEXTURE_2D, GL_TEXTURE_MAX_LEVEL,
                self.lod_level if self.manual_lod else self.max_lod)
            self.texture.setWrapMode(QOpenGLTexture.Repeat if self.repeat
                                     else QOpenGLTexture.ClampToEdge)
            self.vertex_array.bind(); self.buffer.bind(); self.program.bind()
            self.program.setUniformValue("u_texture", 0)
            self.program.setUniformValue("u_texture_size", QVector2D(
                float(self.texture_size), float(self.texture_size)))
            self.program.setUniformValue("u_max_lod", float(self.max_lod))
            self.program.setUniformValue("u_tiling", float(self.tiling))
            self.program.setUniformValue("u_phase", float(self.phase))
            self.program.setUniformValue(
                "u_view", {"final": 0, "mip_color": 1, "lod_heatmap": 2}[self.view_mode])
            self.functions.glDrawArrays(GL_TRIANGLES, 0, 6)
            self.program.release(); self.buffer.release(); self.vertex_array.release()
            self.texture.release()
            self.draw_calls = 1; self.frame_count += 1; self.last_error = ""
        except Exception as error:
            self.last_error = str(error)
        self.draw_ms = (time.perf_counter() - started) * 1000.0
        self.state_changed.emit()

    def runtime_state(self):
        return {
            "context_valid": bool(self.context() and self.context().isValid()),
            "texture_valid": bool(self.texture and self.texture.isCreated()),
            "texture_uploads": self.texture_uploads,
            "geometry_uploads": self.geometry_uploads,
            "draw_calls": self.draw_calls,
            "frame_count": self.frame_count,
            "draw_ms": self.draw_ms,
            "max_lod": self.max_lod,
            "error": self.last_error,
        }


class TextureSamplingPanel(QWidget):
    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.texture_size = 256
        self.base_rgba = build_checker_texture(self.texture_size)
        self.mip_levels, self.backend = generate_mipmaps(
            self.base_rgba, self.texture_size, self.texture_size)
        self.python_mip_levels = python_generate(
            self.base_rgba, self.texture_size, self.texture_size)
        self.viewport = TextureSamplingViewport(
            self.base_rgba, self.texture_size, self)
        self.phase = 0.0
        self._build_ui()
        self.timer = QTimer(self); self.timer.setInterval(33)
        self.timer.timeout.connect(self._animate)
        self.viewport.state_changed.connect(self.refresh)
        self._update_probe()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        intro = QLabel(
            "同一高频纹理在透视压缩平面上对比采样过滤；C++ 生成 Mip 链，"
            "OpenGL 使用真实纹理对象与 fragment derivatives 选择 LOD。")
        intro.setWordWrap(True); layout.addWidget(intro)
        splitter = QSplitter(Qt.Horizontal); splitter.setObjectName("texture_lod_splitter")
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.viewport)
        controls = QWidget(); controls.setMinimumWidth(360)
        controls_layout = QVBoxLayout(controls)

        render_group = QGroupBox("GPU 采样控制")
        render_form = QFormLayout(render_group)
        self.filter_combo = QComboBox()
        for label, value in (("Nearest", "nearest"), ("Bilinear", "bilinear"),
                             ("Trilinear + Mipmap", "trilinear")):
            self.filter_combo.addItem(label, value)
        self.filter_combo.setCurrentIndex(2)
        self.view_combo = QComboBox()
        for label, value in (("最终采样", "final"), ("Mip level 着色", "mip_color"),
                             ("LOD 热力图", "lod_heatmap")):
            self.view_combo.addItem(label, value)
        self.tiling_slider = QSlider(Qt.Horizontal); self.tiling_slider.setRange(1, 32)
        self.tiling_slider.setValue(16)
        self.repeat_check = QCheckBox("Repeat wrap"); self.repeat_check.setChecked(True)
        self.animate_check = QCheckBox("UV phase 动画（观察 shimmer）")
        self.manual_lod_check = QCheckBox("手动固定 Mip level")
        self.lod_slider = QSlider(Qt.Horizontal)
        self.lod_slider.setRange(0, len(self.mip_levels) - 1)
        self.lod_slider.setEnabled(False)
        render_form.addRow("Filter", self.filter_combo)
        render_form.addRow("Debug view", self.view_combo)
        render_form.addRow("Texture tiling", self.tiling_slider)
        render_form.addRow(self.repeat_check)
        render_form.addRow(self.animate_check)
        render_form.addRow(self.manual_lod_check)
        render_form.addRow("Mip level", self.lod_slider)
        controls_layout.addWidget(render_group)

        probe_group = QGroupBox("CPU 数值采样探针")
        probe_form = QFormLayout(probe_group)
        self.probe_u = QDoubleSpinBox(); self.probe_u.setRange(-8.0, 8.0)
        self.probe_u.setDecimals(4); self.probe_u.setValue(0.125)
        self.probe_v = QDoubleSpinBox(); self.probe_v.setRange(-8.0, 8.0)
        self.probe_v.setDecimals(4); self.probe_v.setValue(0.125)
        self.probe_lod = QDoubleSpinBox(); self.probe_lod.setRange(0.0, len(self.mip_levels)-1)
        self.probe_lod.setDecimals(3); self.probe_lod.setValue(2.5)
        probe_form.addRow("U", self.probe_u); probe_form.addRow("V", self.probe_v)
        probe_form.addRow("LOD", self.probe_lod)
        self.probe_label = QLabel(); self.probe_label.setWordWrap(True)
        self.probe_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        probe_form.addRow(self.probe_label)
        controls_layout.addWidget(probe_group)

        mip_group = QGroupBox("C++ 生成的完整 Mip 链")
        mip_layout = QVBoxLayout(mip_group)
        mip_scroll = QScrollArea(); mip_scroll.setWidgetResizable(True)
        mip_content = QWidget(); mip_row = QHBoxLayout(mip_content)
        for index, level in enumerate(self.mip_levels):
            column = QVBoxLayout(); label = QLabel(f"L{index}\n{level.width}×{level.height}")
            label.setAlignment(Qt.AlignCenter)
            preview = QLabel(); preview.setAlignment(Qt.AlignCenter)
            image = QImage(level.rgba, level.width, level.height, level.width * 4,
                           QImage.Format_RGBA8888).copy()
            preview.setPixmap(image_to_pixmap(image, min(112, max(24, level.width))))
            column.addWidget(preview); column.addWidget(label); mip_row.addLayout(column)
        mip_row.addStretch(1); mip_scroll.setWidget(mip_content)
        mip_layout.addWidget(mip_scroll); controls_layout.addWidget(mip_group)

        self.state_label = QLabel(); self.state_label.setWordWrap(True)
        self.state_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        controls_layout.addWidget(self.state_label); controls_layout.addStretch(1)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(controls)
        splitter.addWidget(scroll); splitter.setStretchFactor(0, 3); splitter.setStretchFactor(1, 2)
        splitter.setSizes([760, 420]); layout.addWidget(splitter, 1)

        for control in (self.filter_combo, self.view_combo, self.tiling_slider,
                        self.repeat_check, self.manual_lod_check, self.lod_slider):
            signal = (control.currentIndexChanged if isinstance(control, QComboBox)
                      else control.toggled if isinstance(control, QCheckBox)
                      else control.valueChanged)
            signal.connect(self._controls_changed)
        self.animate_check.toggled.connect(self._animation_changed)
        for control in (self.probe_u, self.probe_v, self.probe_lod):
            control.valueChanged.connect(self._update_probe)

    def _controls_changed(self, *args):
        self.lod_slider.setEnabled(self.manual_lod_check.isChecked())
        self.viewport.set_options(
            filter_mode=self.filter_combo.currentData(),
            view_mode=self.view_combo.currentData(),
            repeat=self.repeat_check.isChecked(),
            manual_lod=self.manual_lod_check.isChecked(),
            lod_level=self.lod_slider.value(),
            tiling=float(self.tiling_slider.value()))
        self._update_probe()

    def _animation_changed(self, checked):
        if checked and self.isVisible(): self.timer.start()
        else: self.timer.stop()

    def _animate(self):
        self.phase = (self.phase + 0.006) % 1.0
        self.viewport.set_options(phase=self.phase)

    def _update_probe(self, *args):
        filter_mode = self.filter_combo.currentData()
        native, backend = sample_texture(
            self.base_rgba, self.texture_size, self.texture_size,
            self.probe_u.value(), self.probe_v.value(), self.probe_lod.value(),
            filter_mode, self.repeat_check.isChecked())
        reference = python_sample(
            self.python_mip_levels,
            self.probe_u.value(), self.probe_v.value(), self.probe_lod.value(),
            filter_mode, self.repeat_check.isChecked())
        difference = tuple(abs(native[index] - reference[index]) for index in range(4))
        self.probe_label.setText(
            f"{backend}: RGBA {native}\nPython: RGBA {reference} · |Δ| {difference}")

    def refresh(self, *args):
        state = self.viewport.runtime_state()
        mip_bytes = sum(len(level.rgba) for level in self.mip_levels)
        error = state["error"] or runtime_error()
        self.state_label.setText(
            f"Mip backend {self.backend} · levels {len(self.mip_levels)} · "
            f"L0 {self.texture_size}² → L{len(self.mip_levels)-1} 1²\n"
            f"CPU chain {mip_bytes / 1024:.1f} KiB · GPU texture ≈"
            f"{mip_bytes / 1024:.1f} KiB · Filter {self.filter_combo.currentText()}\n"
            f"GL context/texture {state['context_valid']}/{state['texture_valid']} · "
            f"uploads texture/VBO {state['texture_uploads']}/{state['geometry_uploads']} · "
            f"frames {state['frame_count']} · draw {state['draw_ms']:.3f} ms"
            + (f"\n错误：{error}" if error else ""))

    def showEvent(self, event):
        super().showEvent(event)
        if self.animate_check.isChecked(): self.timer.start()
        self.refresh(); self.viewport.update()

    def hideEvent(self, event):
        self.timer.stop(); super().hideEvent(event)


def image_to_pixmap(image, edge):
    from PyQt5.QtGui import QPixmap
    return QPixmap.fromImage(image).scaled(edge, edge, Qt.KeepAspectRatio,
                                           Qt.FastTransformation)
