"""M19 texture filtering, mipmap and LOD visualization laboratory."""

import math
import os
import struct
import time

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (QImage, QOpenGLBuffer, QOpenGLShader,
                         QOpenGLShaderProgram, QOpenGLTexture,
                         QOpenGLVertexArrayObject, QOpenGLVersionProfile,
                         QVector2D)
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                             QFileDialog, QGroupBox, QHBoxLayout, QLabel, QPushButton,
                             QScrollArea, QSlider, QSplitter, QVBoxLayout,
                             QWidget, QOpenGLWidget)

from core.native_texture import (generate_mipmaps, generate_mipmaps_srgb,
                                 runtime_error,
                                 sample_anisotropic, sample_texture)
from core.texture_sampling import (build_checker_texture,
                                   generate_mipmaps as python_generate,
                                   generate_mipmaps_srgb as python_generate_srgb,
                                   sample_anisotropic as python_anisotropic,
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
uniform int u_anisotropic;
uniform int u_max_taps;
uniform int u_encode_srgb;
varying vec2 v_uv;

void footprint(out float major_axis, out float minor_axis,
               out float ratio, out vec2 major_direction) {
    vec2 dx = dFdx(v_uv * u_texture_size);
    vec2 dy = dFdy(v_uv * u_texture_size);
    float a = dx.x * dx.x + dy.x * dy.x;
    float b = dx.x * dx.y + dy.x * dy.y;
    float c = dx.y * dx.y + dy.y * dy.y;
    float root = sqrt(max(0.0, (a-c)*(a-c) + 4.0*b*b));
    major_axis = sqrt(max(0.0, 0.5 * (a+c+root)));
    minor_axis = sqrt(max(0.0, 0.5 * (a+c-root)));
    vec2 candidate = abs(b) > 0.000001
        ? vec2(major_axis * major_axis - c, b)
        : (a >= c ? vec2(1.0, 0.0) : vec2(0.0, 1.0));
    major_direction = normalize(candidate);
    ratio = max(1.0, max(1.0, major_axis) / max(1.0, minor_axis));
}

vec3 lod_color(float value) {
    float t = value / max(1.0, u_max_lod);
    return clamp(vec3(1.5 * t, 1.5 - abs(2.0 * t - 1.0) * 1.5,
                      1.5 * (1.0 - t)), 0.0, 1.0);
}

vec3 linear_to_srgb(vec3 value) {
    vec3 low = value * 12.92;
    vec3 high = 1.055 * pow(max(value, vec3(0.0)), vec3(1.0 / 2.4)) - 0.055;
    return vec3(value.r <= 0.0031308 ? low.r : high.r,
                value.g <= 0.0031308 ? low.g : high.g,
                value.b <= 0.0031308 ? low.b : high.b);
}

void main() {
    float major_axis, minor_axis, ratio;
    vec2 major_direction;
    footprint(major_axis, minor_axis, ratio, major_direction);
    float isotropic_lod = clamp(log2(max(1.0, major_axis)), 0.0, u_max_lod);
    float anisotropic_lod = clamp(log2(max(1.0, minor_axis)), 0.0, u_max_lod);
    int taps = int(ceil(ratio - 0.000001));
    if (taps < 1) taps = 1;
    if (taps > u_max_taps) taps = u_max_taps;
    vec4 sampled = vec4(0.0);
    if (u_anisotropic != 0) {
        float span = max(0.0, major_axis - max(1.0, minor_axis));
        float bias = anisotropic_lod - isotropic_lod;
        for (int index = 0; index < 8; ++index) {
            if (index < taps) {
                float offset = ((float(index) + 0.5) / float(taps) - 0.5) * span;
                sampled += texture2D(u_texture,
                    v_uv + major_direction * offset / u_texture_size, bias);
            }
        }
        sampled /= float(taps);
    } else {
        sampled = texture2D(u_texture, v_uv);
        taps = 1;
    }
    float lod = u_anisotropic != 0 ? anisotropic_lod : isotropic_lod;
    vec3 display_sampled = u_encode_srgb != 0
        ? linear_to_srgb(sampled.rgb) : sampled.rgb;
    if (u_view == 1) {
        gl_FragColor = vec4(mix(display_sampled, lod_color(floor(lod + 0.5)), 0.68), 1.0);
    } else if (u_view == 2) {
        gl_FragColor = vec4(lod_color(lod), 1.0);
    } else if (u_view == 3) {
        gl_FragColor = vec4(clamp(vec3(major_axis / 16.0,
            minor_axis / 16.0, 0.5 + 0.5 * major_direction.x), 0.0, 1.0), 1.0);
    } else if (u_view == 4) {
        float heat = clamp(log2(ratio) / 3.0, 0.0, 1.0);
        gl_FragColor = vec4(heat, 1.0 - heat, 0.15, 1.0);
    } else if (u_view == 5) {
        float heat = float(taps - 1) / 7.0;
        gl_FragColor = vec4(heat, 0.3, 1.0 - heat, 1.0);
    } else {
        gl_FragColor = vec4(display_sampled, sampled.a);
    }
}
"""


class TextureSamplingViewport(QOpenGLWidget):
    state_changed = pyqtSignal()

    def __init__(self, base_rgba, texture_width, texture_height,
                 mip_levels, parent=None):
        super().__init__(parent)
        self.base_rgba = bytes(base_rgba)
        self.texture_width = int(texture_width)
        self.texture_height = int(texture_height)
        self.mip_levels = tuple(mip_levels)
        self.color_space = "linear"
        self.filter_mode = "trilinear"
        self.view_mode = "final"
        self.repeat = True
        self.manual_lod = False
        self.anisotropic = False
        self.max_taps = 8
        self.lod_level = 0
        self.tiling = 16.0
        self.phase = 0.0
        self.functions = self.program = self.buffer = self.vertex_array = None
        self.texture = None
        self.texture_pending = True
        self.texture_uploads = self.geometry_uploads = 0
        self.draw_calls = self.frame_count = 0
        self.draw_ms = 0.0
        self.compressed_texture_support = "尚未初始化 OpenGL context"
        self.last_error = ""
        self.setMinimumSize(430, 380)

    @property
    def max_lod(self):
        return len(self.mip_levels) - 1

    def set_source(self, rgba, width, height, mip_levels, color_space):
        self.base_rgba = bytes(rgba)
        self.texture_width, self.texture_height = int(width), int(height)
        self.mip_levels = tuple(mip_levels)
        self.color_space = str(color_space)
        self.texture_pending = True
        self.update()

    def _upload_texture(self):
        if self.texture is not None:
            self.texture.destroy()
        texture = QOpenGLTexture(QOpenGLTexture.Target2D)
        texture.setFormat(QOpenGLTexture.SRGB8_Alpha8 if self.color_space == "srgb"
                          else QOpenGLTexture.RGBA8_UNorm)
        texture.setSize(self.texture_width, self.texture_height)
        texture.setMipLevels(len(self.mip_levels))
        texture.allocateStorage(QOpenGLTexture.RGBA, QOpenGLTexture.UInt8)
        for index, level in enumerate(self.mip_levels):
            texture.setData(index, QOpenGLTexture.RGBA,
                            QOpenGLTexture.UInt8, level.rgba)
        texture.setWrapMode(QOpenGLTexture.Repeat)
        if not texture.isCreated():
            raise RuntimeError("无法创建 texture sampling GPU resource")
        self.texture = texture
        self.texture_pending = False
        self.texture_uploads += 1

    def initializeGL(self):
        try:
            context = self.context()
            extensions = {bytes(value).decode("ascii", "ignore")
                          for value in context.extensions()}
            s3tc = ("GL_EXT_texture_compression_s3tc" in extensions or
                    "GL_EXT_texture_compression_dxt1" in extensions)
            self.compressed_texture_support = (
                "BC1/BC3 驱动能力可用；本阶段仅报告能力，未启用 DDS 直传"
                if s3tc else
                "未发现 S3TC/BC1/BC3 扩展；图片安全回退为 RGBA8")
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
            self.program, self.buffer, self.vertex_array = program, buffer, vertex_array
            self._upload_texture()
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
                    self.buffer is None or self.vertex_array is None):
                return
            if self.texture_pending:
                self._upload_texture()
            if self.texture is None:
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
                float(self.texture_width), float(self.texture_height)))
            self.program.setUniformValue("u_max_lod", float(self.max_lod))
            self.program.setUniformValue("u_tiling", float(self.tiling))
            self.program.setUniformValue("u_phase", float(self.phase))
            self.program.setUniformValue("u_anisotropic", int(self.anisotropic))
            self.program.setUniformValue("u_max_taps", int(self.max_taps))
            self.program.setUniformValue("u_encode_srgb",
                                         1 if self.color_space == "srgb" else 0)
            self.program.setUniformValue(
                "u_view", {"final": 0, "mip_color": 1, "lod_heatmap": 2,
                           "footprint": 3, "anisotropy": 4,
                           "tap_count": 5}[self.view_mode])
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
            "texture_size": (self.texture_width, self.texture_height),
            "color_space": self.color_space,
            "internal_format": ("GL_SRGB8_ALPHA8" if self.color_space == "srgb"
                                else "GL_RGBA8"),
            "compressed_texture_support": self.compressed_texture_support,
            "error": self.last_error,
        }


class TextureSamplingPanel(QWidget):
    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.texture_width = self.texture_height = 256
        self.texture_size = 256
        self.source_name = "程序化 Checker/Grid"
        self.color_mode = "linear"
        self.base_rgba = build_checker_texture(self.texture_width)
        self.mip_levels, self.backend = generate_mipmaps(
            self.base_rgba, self.texture_width, self.texture_height)
        self.python_mip_levels = python_generate(
            self.base_rgba, self.texture_width, self.texture_height)
        self.srgb_mip_levels, self.srgb_backend = generate_mipmaps_srgb(
            self.base_rgba, self.texture_width, self.texture_height)
        self.python_srgb_mip_levels = python_generate_srgb(
            self.base_rgba, self.texture_width, self.texture_height)
        self.linear_mip_levels = self.mip_levels
        self.python_linear_mip_levels = self.python_mip_levels
        self.linear_backend = self.backend
        self.viewport = TextureSamplingViewport(
            self.base_rgba, self.texture_width, self.texture_height,
            self.mip_levels, self)
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

        source_group = QGroupBox("纹理来源与色彩空间")
        source_layout = QVBoxLayout(source_group)
        source_buttons = QHBoxLayout()
        load_image = QPushButton("加载 PNG/JPEG")
        restore_checker = QPushButton("恢复程序纹理")
        load_image.clicked.connect(self._load_image)
        restore_checker.clicked.connect(self._restore_checker)
        source_buttons.addWidget(load_image); source_buttons.addWidget(restore_checker)
        source_layout.addLayout(source_buttons)
        source_form = QFormLayout()
        self.color_space_combo = QComboBox()
        self.color_space_combo.addItem("Legacy / bytes 当作 Linear", "linear")
        self.color_space_combo.addItem("sRGB texture + Linear-light Mips", "srgb")
        self.color_space_combo.addItem("sRGB texture + 错误 Gamma Mips", "srgb_wrong_mip")
        self.color_space_combo.currentIndexChanged.connect(self._color_space_changed)
        source_form.addRow("GPU/Filter 路径", self.color_space_combo)
        source_layout.addLayout(source_form)
        self.source_label = QLabel(); self.source_label.setWordWrap(True)
        self.source_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        source_layout.addWidget(self.source_label)
        controls_layout.addWidget(source_group)

        render_group = QGroupBox("GPU 采样控制")
        render_form = QFormLayout(render_group)
        self.filter_combo = QComboBox()
        for label, value in (("Nearest", "nearest"), ("Bilinear", "bilinear"),
                             ("Trilinear + Mipmap", "trilinear")):
            self.filter_combo.addItem(label, value)
        self.filter_combo.setCurrentIndex(2)
        self.view_combo = QComboBox()
        for label, value in (("最终采样", "final"), ("Mip level 着色", "mip_color"),
                             ("LOD 热力图", "lod_heatmap"),
                             ("Footprint 主/次轴", "footprint"),
                             ("各向异性比率", "anisotropy"),
                             ("实际 Tap 数", "tap_count")):
            self.view_combo.addItem(label, value)
        self.tiling_slider = QSlider(Qt.Horizontal); self.tiling_slider.setRange(1, 32)
        self.tiling_slider.setValue(16)
        self.repeat_check = QCheckBox("Repeat wrap"); self.repeat_check.setChecked(True)
        self.animate_check = QCheckBox("UV phase 动画（观察 shimmer）")
        self.manual_lod_check = QCheckBox("手动固定 Mip level")
        self.anisotropic_check = QCheckBox("手写各向异性过滤")
        self.tap_combo = QComboBox()
        for taps in (1, 2, 4, 8):
            self.tap_combo.addItem(f"{taps}×", taps)
        self.tap_combo.setCurrentIndex(3)
        self.lod_slider = QSlider(Qt.Horizontal)
        self.lod_slider.setRange(0, len(self.mip_levels) - 1)
        self.lod_slider.setEnabled(False)
        render_form.addRow("Filter", self.filter_combo)
        render_form.addRow("Debug view", self.view_combo)
        render_form.addRow("Texture tiling", self.tiling_slider)
        render_form.addRow(self.repeat_check)
        render_form.addRow(self.animate_check)
        render_form.addRow(self.anisotropic_check)
        render_form.addRow("Max anisotropic taps", self.tap_combo)
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
        self.derivative_spins = []
        defaults = (8.0 / self.texture_size, 0.0, 0.0,
                    2.0 / self.texture_size)
        for label, value in zip(("dU/dx", "dV/dx", "dU/dy", "dV/dy"), defaults):
            control = QDoubleSpinBox(); control.setRange(-1.0, 1.0)
            control.setDecimals(6); control.setSingleStep(1.0 / self.texture_size)
            control.setValue(value); self.derivative_spins.append(control)
            probe_form.addRow(label, control)
        self.footprint_label = QLabel(); self.footprint_label.setWordWrap(True)
        self.footprint_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        probe_form.addRow(self.footprint_label)
        self.probe_label = QLabel(); self.probe_label.setWordWrap(True)
        self.probe_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        probe_form.addRow(self.probe_label)
        controls_layout.addWidget(probe_group)

        mip_group = QGroupBox("C++ 生成的完整 Mip 链")
        mip_layout = QVBoxLayout(mip_group)
        mip_scroll = QScrollArea(); mip_scroll.setWidgetResizable(True)
        self.mip_scroll = mip_scroll
        self._rebuild_mip_preview()
        mip_layout.addWidget(mip_scroll); controls_layout.addWidget(mip_group)

        self.state_label = QLabel(); self.state_label.setWordWrap(True)
        self.state_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        controls_layout.addWidget(self.state_label); controls_layout.addStretch(1)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(controls)
        splitter.addWidget(scroll); splitter.setStretchFactor(0, 3); splitter.setStretchFactor(1, 2)
        splitter.setSizes([760, 420]); layout.addWidget(splitter, 1)

        for control in (self.filter_combo, self.view_combo, self.tap_combo,
                        self.tiling_slider, self.repeat_check,
                        self.anisotropic_check, self.manual_lod_check,
                        self.lod_slider):
            signal = (control.currentIndexChanged if isinstance(control, QComboBox)
                      else control.toggled if isinstance(control, QCheckBox)
                      else control.valueChanged)
            signal.connect(self._controls_changed)
        self.animate_check.toggled.connect(self._animation_changed)
        for control in (self.probe_u, self.probe_v, self.probe_lod,
                        *self.derivative_spins):
            control.valueChanged.connect(self._update_probe)

    def _rebuild_mip_preview(self):
        content = QWidget(); row = QHBoxLayout(content)
        for index, level in enumerate(self.mip_levels):
            column = QVBoxLayout()
            label = QLabel(f"L{index}\n{level.width}×{level.height}")
            label.setAlignment(Qt.AlignCenter)
            preview = QLabel(); preview.setAlignment(Qt.AlignCenter)
            image = QImage(level.rgba, level.width, level.height,
                           level.width * 4, QImage.Format_RGBA8888).copy()
            preview.setPixmap(image_to_pixmap(
                image, min(112, max(24, max(level.width, level.height)))))
            column.addWidget(preview); column.addWidget(label); row.addLayout(column)
        row.addStretch(1)
        self.mip_scroll.setWidget(content)

    def _apply_source(self, rgba, width, height, source_name):
        width, height = int(width), int(height)
        if width <= 0 or height <= 0 or width > 2048 or height > 2048:
            raise ValueError("图片尺寸必须位于 1..2048")
        if len(rgba) != width * height * 4:
            raise ValueError("RGBA8 图片缓冲尺寸不匹配")
        linear_levels, linear_backend = generate_mipmaps(rgba, width, height)
        srgb_levels, srgb_backend = generate_mipmaps_srgb(rgba, width, height)
        python_linear = python_generate(rgba, width, height)
        python_srgb = python_generate_srgb(rgba, width, height)
        self.base_rgba = bytes(rgba)
        self.texture_width, self.texture_height = width, height
        self.texture_size = max(width, height)
        self.source_name = str(source_name)
        self.linear_mip_levels, self.linear_backend = linear_levels, linear_backend
        self.python_linear_mip_levels = python_linear
        self.srgb_mip_levels, self.srgb_backend = srgb_levels, srgb_backend
        self.python_srgb_mip_levels = python_srgb
        self._color_space_changed()

    def _load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "加载纹理图片", "", "Images (*.png *.jpg *.jpeg)")
        if not path:
            return
        try:
            if os.path.getsize(path) > 64 * 1024 * 1024:
                raise ValueError("图片文件超过 64 MiB 安全上限")
            image = QImage(path)
            if image.isNull():
                raise ValueError("Qt 无法解码该图片")
            if image.width() > 2048 or image.height() > 2048:
                raise ValueError("图片像素尺寸超过 2048×2048 安全上限")
            converted = image.convertToFormat(QImage.Format_RGBA8888)
            pointer = converted.bits(); pointer.setsize(converted.byteCount())
            self._apply_source(bytes(pointer), converted.width(), converted.height(),
                               os.path.basename(path))
        except (OSError, ValueError) as error:
            self.viewport.last_error = f"图片加载失败：{error}"
            self.refresh()

    def _restore_checker(self):
        self._apply_source(build_checker_texture(256), 256, 256,
                           "程序化 Checker/Grid")

    def _color_space_changed(self, *args):
        if not hasattr(self, "color_space_combo"):
            return
        self.color_mode = self.color_space_combo.currentData()
        correct = self.color_mode == "srgb"
        self.mip_levels = self.srgb_mip_levels if correct else self.linear_mip_levels
        self.python_mip_levels = (self.python_srgb_mip_levels if correct
                                  else self.python_linear_mip_levels)
        self.backend = self.srgb_backend if correct else self.linear_backend
        gpu_space = "srgb" if self.color_mode != "linear" else "linear"
        self.viewport.set_source(self.base_rgba, self.texture_width,
                                 self.texture_height, self.mip_levels, gpu_space)
        if hasattr(self, "lod_slider"):
            maximum = len(self.mip_levels) - 1
            self.lod_slider.setMaximum(maximum)
            self.probe_lod.setMaximum(maximum)
            self._rebuild_mip_preview()
            self._update_probe(); self.refresh()

    def _controls_changed(self, *args):
        self.lod_slider.setEnabled(self.manual_lod_check.isChecked())
        self.viewport.set_options(
            filter_mode=self.filter_combo.currentData(),
            view_mode=self.view_combo.currentData(),
            repeat=self.repeat_check.isChecked(),
            manual_lod=self.manual_lod_check.isChecked(),
            lod_level=self.lod_slider.value(),
            anisotropic=self.anisotropic_check.isChecked(),
            max_taps=self.tap_combo.currentData(),
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
        if self.color_mode == "srgb":
            native = python_sample(
                self.mip_levels, self.probe_u.value(), self.probe_v.value(),
                self.probe_lod.value(), filter_mode,
                self.repeat_check.isChecked())
            backend = f"{self.backend} Mips + reference sampler"
        else:
            native, backend = sample_texture(
                self.base_rgba, self.texture_width, self.texture_height,
                self.probe_u.value(), self.probe_v.value(), self.probe_lod.value(),
                filter_mode, self.repeat_check.isChecked())
        reference = python_sample(
            self.python_mip_levels,
            self.probe_u.value(), self.probe_v.value(), self.probe_lod.value(),
            filter_mode, self.repeat_check.isChecked())
        difference = tuple(abs(native[index] - reference[index]) for index in range(4))
        derivatives = tuple(control.value() for control in self.derivative_spins)
        if self.color_mode == "srgb":
            aniso_native, footprint = python_anisotropic(
                self.mip_levels, self.probe_u.value(), self.probe_v.value(),
                *derivatives, self.tap_combo.currentData(),
                self.repeat_check.isChecked())
            aniso_backend = f"{self.backend} Mips + reference sampler"
        else:
            aniso_native, footprint, aniso_backend = sample_anisotropic(
                self.base_rgba, self.texture_width, self.texture_height,
                self.probe_u.value(), self.probe_v.value(), *derivatives,
                self.tap_combo.currentData(), self.repeat_check.isChecked())
        aniso_reference, reference_footprint = python_anisotropic(
            self.python_mip_levels, self.probe_u.value(), self.probe_v.value(),
            *derivatives, self.tap_combo.currentData(), self.repeat_check.isChecked())
        aniso_difference = tuple(abs(aniso_native[index] - aniso_reference[index])
                                 for index in range(4))
        self.probe_label.setText(
            f"Isotropic {backend}: {native} · Python {reference} · |Δ| {difference}\n"
            f"Anisotropic {aniso_backend}: {aniso_native} · Python "
            f"{aniso_reference} · |Δ| {aniso_difference}")
        self.footprint_label.setText(
            f"Ellipse major/minor {footprint.major:.3f}/{footprint.minor:.3f} texels · "
            f"ratio {footprint.ratio:.2f}:1 · taps {footprint.taps}/"
            f"{self.tap_combo.currentData()}\n"
            f"LOD isotropic/aniso {footprint.isotropic_lod:.3f}/"
            f"{footprint.anisotropic_lod:.3f} · major dir "
            f"({footprint.direction_u:.3f}, {footprint.direction_v:.3f})")

    def refresh(self, *args):
        state = self.viewport.runtime_state()
        mip_bytes = sum(len(level.rgba) for level in self.mip_levels)
        gamma_difference = sum(abs(first - second)
            for linear, srgb in zip(self.linear_mip_levels[1:], self.srgb_mip_levels[1:])
            for first, second in zip(linear.rgba, srgb.rgba))
        error = state["error"] or runtime_error()
        self.source_label.setText(
            f"{self.source_name} · {self.texture_width}×{self.texture_height} RGBA8\n"
            f"模式 {self.color_space_combo.currentText()} · GPU {state['internal_format']} · "
            f"Mip RGB absolute byte difference {gamma_difference}")
        self.state_label.setText(
            f"Mip backend {self.backend} · levels {len(self.mip_levels)} · "
            f"L0 {self.texture_width}×{self.texture_height} → "
            f"L{len(self.mip_levels)-1} {self.mip_levels[-1].width}×"
            f"{self.mip_levels[-1].height}\n"
            f"CPU chain {mip_bytes / 1024:.1f} KiB · GPU texture ≈"
            f"{mip_bytes / 1024:.1f} KiB · Filter {self.filter_combo.currentText()}\n"
            f"Anisotropic {'ON' if self.anisotropic_check.isChecked() else 'OFF'} · "
            f"fetch budget ≤ {self.tap_combo.currentData()} taps/fragment · "
            f"Debug {self.view_combo.currentText()}\n"
            f"GL context/texture {state['context_valid']}/{state['texture_valid']} · "
            f"uploads texture/VBO {state['texture_uploads']}/{state['geometry_uploads']} · "
            f"frames {state['frame_count']} · draw {state['draw_ms']:.3f} ms\n"
            f"压缩纹理：{state['compressed_texture_support']}"
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
