"""C++ exact distance transform + OpenGL SDF visualization laboratory."""

import math
import struct
import time

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import (QColor, QFont, QImage, QOpenGLBuffer, QOpenGLShader,
                         QOpenGLShaderProgram, QOpenGLTexture,
                         QOpenGLVertexArrayObject, QOpenGLVersionProfile, QPainter)
from PyQt5.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                             QHBoxLayout, QLabel, QPushButton, QScrollArea,
                             QSlider, QVBoxLayout, QWidget, QOpenGLWidget)

from core.distance_field import encode_signed_distance_rgba8
from core.native_distance_field import signed_distance_field
from .pipeline3d_panel import _PipelineGLFunctions


GL_COLOR_BUFFER_BIT = 0x00004000
GL_FLOAT = 0x1406
GL_TRIANGLES = 0x0004

VERTEX_SHADER = """
attribute vec2 a_position;
attribute vec2 a_uv;
varying vec2 v_uv;
void main() { v_uv = a_uv; gl_Position = vec4(a_position, 0.0, 1.0); }
"""

FRAGMENT_SHADER = """
uniform sampler2D u_bitmap;
uniform sampler2D u_sdf;
uniform float u_scale;
uniform float u_range;
uniform float u_outline;
uniform float u_glow;
uniform int u_view;
varying vec2 v_uv;
float field(vec2 uv) { return (texture2D(u_sdf, uv).r - 0.5) * 2.0 * u_range; }
void main() {
    bool sdf_side = v_uv.x >= 0.5;
    vec2 cell_uv = vec2(sdf_side ? (v_uv.x - 0.5) * 2.0 : v_uv.x * 2.0, v_uv.y);
    vec2 uv = (cell_uv - 0.5) / u_scale + 0.5;
    bool outside = any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)));
    float bitmap = outside ? 0.0 : texture2D(u_bitmap, uv).a;
    float distance = outside ? -u_range : field(uv);
    float width = max(fwidth(distance), 0.35);
    float fill = smoothstep(-width, width, distance);
    float outline = smoothstep(-u_outline-width, -u_outline+width, distance) - fill;
    float glow = exp(-max(0.0, -distance) / max(u_glow, 0.1)) * (1.0-fill);
    vec3 color;
    if (u_view == 1) color = vec3(sdf_side ? step(0.0, distance) : bitmap);
    else if (u_view == 2) color = vec3(0.5 + 0.5 * clamp(distance/u_range, -1.0, 1.0),
                                      distance >= 0.0 ? 0.75 : 0.18,
                                      distance < 0.0 ? 0.78 : 0.20);
    else if (u_view == 3) {
        float contour = 1.0 - smoothstep(0.0, width*1.8, abs(mod(distance+2.0,4.0)-2.0));
        color = mix(vec3(0.06,0.08,0.11), vec3(0.15,0.9,0.72), contour);
    } else if (!sdf_side) color = vec3(bitmap);
    else color = vec3(0.12,0.78,1.0)*fill + vec3(1.0,0.48,0.12)*outline +
                 vec3(0.32,0.45,1.0)*glow*0.65;
    if (abs(v_uv.x - 0.5) < 0.0025) color = vec3(0.95,0.8,0.15);
    gl_FragColor = vec4(color, 1.0);
}
"""


def build_mask(source, size=128):
    image = QImage(size, size, QImage.Format_RGBA8888)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen); painter.setBrush(QColor(255, 255, 255, 255))
    if source == "glyph":
        painter.setPen(QColor(255, 255, 255, 255))
        painter.setFont(QFont("Arial", int(size * 0.72), QFont.Bold))
        painter.drawText(image.rect(), Qt.AlignCenter, "G")
    elif source == "star":
        from PyQt5.QtGui import QPolygonF
        from PyQt5.QtCore import QPointF
        points = []
        for index in range(10):
            angle = -math.pi / 2.0 + index * math.pi / 5.0
            radius = size * (0.40 if index % 2 == 0 else 0.18)
            points.append(QPointF(size/2 + math.cos(angle)*radius,
                                  size/2 + math.sin(angle)*radius))
        painter.drawPolygon(QPolygonF(points))
    else:
        painter.drawEllipse(int(size*0.16), int(size*0.16), int(size*0.68), int(size*0.68))
    painter.end()
    pointer = image.bits(); pointer.setsize(image.byteCount())
    rgba = bytes(pointer)
    mask = tuple(rgba[index + 3] >= 128 for index in range(0, len(rgba), 4))
    return rgba, mask


class SdfViewport(QOpenGLWidget):
    state_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.source = "glyph"; self.distance_range = 16.0
        self.scale = 1.0; self.outline = 2.0; self.glow = 5.0; self.view_mode = 0
        self.functions = self.program = self.vbo = self.vao = None
        self.bitmap_texture = self.sdf_texture = None
        self.pending = True; self.rebuilds = self.uploads = self.frames = 0
        self.generation_ms = self.draw_ms = 0.0; self.backend = ""
        self.last_error = ""; self.setMinimumSize(620, 440)
        self._rebuild_field()

    def _rebuild_field(self):
        started = time.perf_counter()
        self.bitmap_rgba, mask = build_mask(self.source)
        self.distances, self.backend = signed_distance_field(mask, 128, 128)
        self.sdf_rgba = encode_signed_distance_rgba8(self.distances, self.distance_range)
        self.generation_ms = (time.perf_counter() - started) * 1000.0
        self.rebuilds += 1; self.pending = True; self.update()

    def set_source(self, source): self.source = source; self._rebuild_field()
    def set_range(self, value): self.distance_range = float(value); self._rebuild_field()

    def _texture(self, rgba):
        texture = QOpenGLTexture(QOpenGLTexture.Target2D)
        texture.setFormat(QOpenGLTexture.RGBA8_UNorm); texture.setSize(128, 128)
        texture.allocateStorage(QOpenGLTexture.RGBA, QOpenGLTexture.UInt8)
        texture.setData(QOpenGLTexture.RGBA, QOpenGLTexture.UInt8, rgba)
        texture.setMinMagFilters(QOpenGLTexture.Linear, QOpenGLTexture.Linear)
        texture.setWrapMode(QOpenGLTexture.ClampToEdge)
        return texture

    def _upload(self):
        for texture in (self.bitmap_texture, self.sdf_texture):
            if texture is not None: texture.destroy()
        self.bitmap_texture = self._texture(self.bitmap_rgba)
        self.sdf_texture = self._texture(self.sdf_rgba)
        self.uploads += 2; self.pending = False

    def initializeGL(self):
        try:
            context = self.context(); profile = QOpenGLVersionProfile(context.format())
            self.functions = context.versionFunctions(profile) or _PipelineGLFunctions(context)
            self.functions.initializeOpenGLFunctions()
            self.program = QOpenGLShaderProgram()
            if not self.program.addShaderFromSourceCode(QOpenGLShader.Vertex, VERTEX_SHADER):
                raise RuntimeError(self.program.log())
            if not self.program.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAGMENT_SHADER):
                raise RuntimeError(self.program.log())
            self.program.bindAttributeLocation("a_position", 0)
            self.program.bindAttributeLocation("a_uv", 1)
            if not self.program.link(): raise RuntimeError(self.program.log())
            vertices = (-1,-1,0,1, 1,-1,1,1, 1,1,1,0, -1,-1,0,1, 1,1,1,0, -1,1,0,0)
            payload = struct.pack("<24f", *vertices)
            self.vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer); self.vao = QOpenGLVertexArrayObject()
            if not self.vbo.create() or not self.vao.create(): raise RuntimeError("无法创建 SDF VAO/VBO")
            self.vao.bind(); self.vbo.bind(); self.vbo.allocate(payload, len(payload)); self.program.bind()
            for name, offset in (("a_position", 0), ("a_uv", 8)):
                location = self.program.attributeLocation(name); self.program.enableAttributeArray(location)
                self.program.setAttributeBuffer(location, GL_FLOAT, offset, 2, 16)
            self.program.release(); self.vbo.release(); self.vao.release(); self._upload()
        except Exception as error: self.last_error = str(error)
        self.state_changed.emit()

    def paintGL(self):
        started = time.perf_counter()
        try:
            if not self.functions or not self.program: return
            if self.pending: self._upload()
            self.functions.glViewport(0, 0, max(1,self.width()), max(1,self.height()))
            self.functions.glClearColor(0.035,0.05,0.075,1); self.functions.glClear(GL_COLOR_BUFFER_BIT)
            self.bitmap_texture.bind(0); self.sdf_texture.bind(1); self.vao.bind(); self.program.bind()
            for name, value in (("u_bitmap",0),("u_sdf",1),("u_view",self.view_mode)):
                self.program.setUniformValue(name, value)
            for name, value in (("u_scale",self.scale),("u_range",self.distance_range),
                                ("u_outline",self.outline),("u_glow",self.glow)):
                self.program.setUniformValue(name, float(value))
            self.functions.glDrawArrays(GL_TRIANGLES,0,6)
            self.program.release(); self.vao.release(); self.sdf_texture.release(); self.bitmap_texture.release()
            self.frames += 1; self.last_error = ""
        except Exception as error: self.last_error = str(error)
        self.draw_ms = (time.perf_counter()-started)*1000.0; self.state_changed.emit()

    def runtime_state(self):
        return {"valid": bool(self.context() and self.context().isValid() and self.sdf_texture),
                "backend": self.backend, "generation_ms": self.generation_ms,
                "rebuilds": self.rebuilds, "uploads": self.uploads, "frames": self.frames,
                "draw_ms": self.draw_ms, "scale": self.scale, "view": self.view_mode,
                "error": self.last_error}


class SdfPanel(QWidget):
    def __init__(self, canvas=None, parent=None):
        super().__init__(parent); self.canvas = canvas; self.viewport = SdfViewport(self)
        body = QWidget(); layout = QVBoxLayout(body)
        explanation = QLabel("同一 128² mask：左侧 bitmap coverage，右侧 C++ EDT 生成的 signed distance。缩放只更新 uniform，不重建纹理。")
        explanation.setWordWrap(True); layout.addWidget(explanation)
        controls = QGroupBox("距离场控制"); form = QFormLayout(controls)
        self.source_combo = QComboBox(); self.source_combo.addItem("动态字形 G", "glyph"); self.source_combo.addItem("圆形", "circle"); self.source_combo.addItem("星形", "star")
        self.view_combo = QComboBox(); self.view_combo.addItems(("Bitmap / SDF 最终对照","二值 Mask","Signed Distance","等值线"))
        self.scale_slider = QSlider(Qt.Horizontal); self.scale_slider.setRange(25,800); self.scale_slider.setValue(100)
        self.range_spin = QDoubleSpinBox(); self.range_spin.setRange(2,32); self.range_spin.setValue(16)
        self.outline_spin = QDoubleSpinBox(); self.outline_spin.setRange(0,8); self.outline_spin.setValue(2)
        self.glow_spin = QDoubleSpinBox(); self.glow_spin.setRange(0.1,16); self.glow_spin.setValue(5)
        for label, widget in (("源 Mask",self.source_combo),("调试视图",self.view_combo),("缩放 0.25×..8×",self.scale_slider),("SDF range",self.range_spin),("描边 px",self.outline_spin),("发光 range",self.glow_spin)): form.addRow(label,widget)
        layout.addWidget(controls); layout.addWidget(self.viewport,1)
        self.state_label = QLabel(); self.state_label.setWordWrap(True); layout.addWidget(self.state_label)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(body)
        outer = QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); outer.addWidget(scroll)
        self.source_combo.currentIndexChanged.connect(lambda: (self.viewport.set_source(self.source_combo.currentData()), self.refresh()))
        self.view_combo.currentIndexChanged.connect(lambda value: (setattr(self.viewport,"view_mode",value),self.viewport.update(),self.refresh()))
        self.scale_slider.valueChanged.connect(lambda value: (setattr(self.viewport,"scale",value/100.0),self.viewport.update(),self.refresh()))
        self.range_spin.valueChanged.connect(lambda value: (self.viewport.set_range(value),self.refresh()))
        self.outline_spin.valueChanged.connect(lambda value: (setattr(self.viewport,"outline",value),self.viewport.update(),self.refresh()))
        self.glow_spin.valueChanged.connect(lambda value: (setattr(self.viewport,"glow",value),self.viewport.update(),self.refresh()))
        self.viewport.state_changed.connect(self.refresh); self.refresh()

    def refresh(self, *args):
        state = self.viewport.runtime_state()
        self.state_label.setText(f"{state['backend']} · 128×128 RGBA8 encoded SDF · range ±{self.viewport.distance_range:g}px\n生成 {state['generation_ms']:.3f} ms · rebuilds {state['rebuilds']} · GPU uploads {state['uploads']} · frames {state['frames']} · draw {state['draw_ms']:.3f} ms" + (f"\n错误：{state['error']}" if state['error'] else ""))
