"""Independent OpenGL 3D viewport and controls for M17."""

import ctypes
import os
import struct
import time

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import (QMatrix4x4, QOpenGLBuffer, QOpenGLContext,
                         QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat,
                         QOpenGLShader, QOpenGLShaderProgram, QOpenGLVersionProfile,
                         QOpenGLVertexArrayObject, QImage, QPixmap, QVector3D)
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                             QGroupBox, QHBoxLayout, QLabel, QOpenGLWidget,
                             QPushButton, QScrollArea, QSpinBox, QSplitter,
                             QTabWidget, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget)

from core.mesh3d import MESH_VERTEX_STRIDE
from core.mesh_source import selected_mesh_source
from core.native_mesh import cube_mesh, extrude_mesh
from core.native_rasterizer import software_rasterize
from core.raster_comparison import compare_rgba, pixel_probe
from core.pipeline3d import (ATTACHMENT_MODES, Pipeline3DConfig, VIEW_MODES,
                             camera_position, light_matrices, pipeline_matrices,
                             scene_lights, trace_pipeline_vertex)
from core.software_pipeline import raster_input_vertices


GL_COLOR_BUFFER_BIT = 0x00004000
GL_DEPTH_BUFFER_BIT = 0x00000100
GL_DEPTH_TEST = 0x0B71
GL_CULL_FACE = 0x0B44
GL_BACK = 0x0405
GL_CCW = 0x0901
GL_FRONT_AND_BACK = 0x0408
GL_LINE = 0x1B01
GL_FILL = 0x1B02
GL_LESS = 0x0201
GL_FLOAT = 0x1406
GL_TRIANGLES = 0x0004
GL_TEXTURE0 = 0x84C0
GL_TEXTURE_2D = 0x0DE1
GL_RGBA8 = 0x8058
GL_RGBA16F = 0x881A
GL_FRAMEBUFFER = 0x8D40
GL_COLOR_ATTACHMENT0 = 0x8CE0

VERTEX_SHADER = """
attribute vec3 a_position;
attribute vec3 a_normal;
uniform mat4 u_model;
uniform mat4 u_view;
uniform mat4 u_projection;
uniform mat4 u_light_view_projection;
varying vec3 v_normal;
varying vec3 v_world;
varying vec4 v_light_clip;
void main() {
    vec4 world = u_model * vec4(a_position, 1.0);
    v_world = world.xyz;
    v_normal = normalize(mat3(u_model) * a_normal);
    v_light_clip = u_light_view_projection * world;
    gl_Position = u_projection * u_view * world;
}
"""

FRAGMENT_SHADER = """
#ifdef GL_ES
precision mediump float;
#endif
uniform int u_mode;
uniform int u_shadow_enabled;
uniform int u_pcf_radius;
uniform float u_shadow_bias;
uniform float u_shadow_texel;
uniform float u_ambient;
uniform float u_diffuse;
uniform float u_specular;
uniform float u_shininess;
uniform vec3 u_light_position;
uniform vec3 u_camera_position;
uniform vec3 u_base_color;
uniform sampler2D u_shadow_map;
uniform int u_light_count;
uniform vec3 u_light_position0; uniform vec3 u_light_color0;
uniform vec3 u_light_position1; uniform vec3 u_light_color1;
uniform vec3 u_light_position2; uniform vec3 u_light_color2;
uniform vec3 u_light_position3; uniform vec3 u_light_color3;
uniform vec3 u_light_position4; uniform vec3 u_light_color4;
uniform vec3 u_light_position5; uniform vec3 u_light_color5;
uniform vec3 u_light_position6; uniform vec3 u_light_color6;
uniform vec3 u_light_position7; uniform vec3 u_light_color7;
varying vec3 v_normal;
varying vec3 v_world;
varying vec4 v_light_clip;

float shadow_factor() {
    vec3 projected = v_light_clip.xyz / v_light_clip.w;
    projected = projected * 0.5 + 0.5;
    if (projected.z <= 0.0 || projected.z >= 1.0 ||
        projected.x <= 0.0 || projected.x >= 1.0 ||
        projected.y <= 0.0 || projected.y >= 1.0) return 0.0;
    float blocked = 0.0;
    float samples = 0.0;
    for (int y = -2; y <= 2; ++y) {
        for (int x = -2; x <= 2; ++x) {
            if (x >= -u_pcf_radius && x <= u_pcf_radius &&
                y >= -u_pcf_radius && y <= u_pcf_radius) {
                float closest = texture2D(u_shadow_map,
                    projected.xy + vec2(float(x), float(y)) * u_shadow_texel).r;
                blocked += projected.z - u_shadow_bias > closest ? 1.0 : 0.0;
                samples += 1.0;
            }
        }
    }
    return samples > 0.0 ? blocked / samples : 0.0;
}

vec3 light_term(vec3 position, vec3 color, vec3 normal, vec3 view_dir,
                float shadow) {
    vec3 light_dir = normalize(position - v_world);
    vec3 halfway_dir = normalize(light_dir + view_dir);
    float lambert = max(dot(normal, light_dir), 0.0);
    float highlight = lambert > 0.0
        ? pow(max(dot(normal, halfway_dir), 0.0), u_shininess) : 0.0;
    return (u_base_color * u_diffuse * lambert +
            vec3(u_specular * highlight)) * color * (1.0 - shadow);
}
void main() {
    vec3 normal = normalize(v_normal);
    if (u_mode == 4) {
        gl_FragColor = vec4(vec3(gl_FragCoord.z), 1.0);
    } else if (u_mode == 5) {
        vec3 projected = v_light_clip.xyz / v_light_clip.w * 0.5 + 0.5;
        gl_FragColor = vec4(vec3(texture2D(u_shadow_map, projected.xy).r), 1.0);
    } else if (u_mode == 1) {
        gl_FragColor = vec4(0.08, 0.82, 0.95, 1.0);
    } else if (u_mode == 2) {
        gl_FragColor = vec4(normal * 0.5 + 0.5, 1.0);
    } else if (u_mode == 3) {
        gl_FragColor = vec4(vec3(gl_FragCoord.z), 1.0);
    } else {
        vec3 view_dir = normalize(u_camera_position - v_world);
        float shadow = u_shadow_enabled != 0 ? shadow_factor() : 0.0;
        vec3 lit = u_base_color * u_ambient;
        if (u_light_count > 0) lit += light_term(u_light_position0, u_light_color0, normal, view_dir, shadow);
        if (u_light_count > 1) lit += light_term(u_light_position1, u_light_color1, normal, view_dir, 0.0);
        if (u_light_count > 2) lit += light_term(u_light_position2, u_light_color2, normal, view_dir, 0.0);
        if (u_light_count > 3) lit += light_term(u_light_position3, u_light_color3, normal, view_dir, 0.0);
        if (u_light_count > 4) lit += light_term(u_light_position4, u_light_color4, normal, view_dir, 0.0);
        if (u_light_count > 5) lit += light_term(u_light_position5, u_light_color5, normal, view_dir, 0.0);
        if (u_light_count > 6) lit += light_term(u_light_position6, u_light_color6, normal, view_dir, 0.0);
        if (u_light_count > 7) lit += light_term(u_light_position7, u_light_color7, normal, view_dir, 0.0);
        gl_FragColor = vec4(lit, 1.0);
    }
}
"""

GBUFFER_FRAGMENT_SHADER = """
#extension GL_ARB_draw_buffers : enable
#ifdef GL_ES
precision highp float;
#endif
uniform vec3 u_base_color;
varying vec3 v_normal;
varying vec3 v_world;
void main() {
    gl_FragData[0] = vec4(v_world, 1.0);
    gl_FragData[1] = vec4(normalize(v_normal) * 0.5 + 0.5, 1.0);
    gl_FragData[2] = vec4(u_base_color, 1.0);
}
"""

QUAD_VERTEX_SHADER = """
attribute vec2 a_position;
attribute vec2 a_uv;
varying vec2 v_uv;
void main() { v_uv = a_uv; gl_Position = vec4(a_position, 0.0, 1.0); }
"""

DEFERRED_FRAGMENT_SHADER = """
#ifdef GL_ES
precision highp float;
#endif
uniform sampler2D u_g_position;
uniform sampler2D u_g_normal;
uniform sampler2D u_g_albedo;
uniform sampler2D u_shadow_map;
uniform mat4 u_light_view_projection;
uniform vec3 u_camera_position;
uniform float u_ambient; uniform float u_diffuse;
uniform float u_specular; uniform float u_shininess;
uniform int u_shadow_enabled; uniform float u_shadow_bias;
uniform float u_shadow_texel; uniform int u_pcf_radius;
uniform int u_light_count;
uniform vec3 u_light_position0; uniform vec3 u_light_color0;
uniform vec3 u_light_position1; uniform vec3 u_light_color1;
uniform vec3 u_light_position2; uniform vec3 u_light_color2;
uniform vec3 u_light_position3; uniform vec3 u_light_color3;
uniform vec3 u_light_position4; uniform vec3 u_light_color4;
uniform vec3 u_light_position5; uniform vec3 u_light_color5;
uniform vec3 u_light_position6; uniform vec3 u_light_color6;
uniform vec3 u_light_position7; uniform vec3 u_light_color7;
varying vec2 v_uv;

float primary_shadow(vec3 world) {
    vec4 clip = u_light_view_projection * vec4(world, 1.0);
    vec3 projected = clip.xyz / clip.w * 0.5 + 0.5;
    if (projected.z <= 0.0 || projected.z >= 1.0 ||
        projected.x <= 0.0 || projected.x >= 1.0 ||
        projected.y <= 0.0 || projected.y >= 1.0) return 0.0;
    float blocked = 0.0; float samples = 0.0;
    for (int y = -2; y <= 2; ++y) for (int x = -2; x <= 2; ++x) {
        if (x >= -u_pcf_radius && x <= u_pcf_radius &&
            y >= -u_pcf_radius && y <= u_pcf_radius) {
            float closest = texture2D(u_shadow_map,
                projected.xy + vec2(float(x), float(y)) * u_shadow_texel).r;
            blocked += projected.z - u_shadow_bias > closest ? 1.0 : 0.0;
            samples += 1.0;
        }
    }
    return blocked / max(samples, 1.0);
}
vec3 term(vec3 position, vec3 color, vec3 world, vec3 normal,
          vec3 albedo, vec3 view_dir, float shadow) {
    vec3 light_dir = normalize(position - world);
    vec3 halfway_dir = normalize(light_dir + view_dir);
    float lambert = max(dot(normal, light_dir), 0.0);
    float highlight = lambert > 0.0 ?
        pow(max(dot(normal, halfway_dir), 0.0), u_shininess) : 0.0;
    return (albedo * u_diffuse * lambert + vec3(u_specular * highlight))
        * color * (1.0 - shadow);
}
void main() {
    vec3 world = texture2D(u_g_position, v_uv).xyz;
    vec3 encoded_normal = texture2D(u_g_normal, v_uv).xyz;
    vec3 albedo = texture2D(u_g_albedo, v_uv).xyz;
    if (dot(encoded_normal, encoded_normal) < 0.001) {
        gl_FragColor = vec4(0.055, 0.075, 0.105, 1.0); return;
    }
    vec3 normal = normalize(encoded_normal * 2.0 - 1.0);
    vec3 view_dir = normalize(u_camera_position - world);
    float shadow = u_shadow_enabled != 0 ? primary_shadow(world) : 0.0;
    vec3 lit = albedo * u_ambient;
    if (u_light_count > 0) lit += term(u_light_position0,u_light_color0,world,normal,albedo,view_dir,shadow);
    if (u_light_count > 1) lit += term(u_light_position1,u_light_color1,world,normal,albedo,view_dir,0.0);
    if (u_light_count > 2) lit += term(u_light_position2,u_light_color2,world,normal,albedo,view_dir,0.0);
    if (u_light_count > 3) lit += term(u_light_position3,u_light_color3,world,normal,albedo,view_dir,0.0);
    if (u_light_count > 4) lit += term(u_light_position4,u_light_color4,world,normal,albedo,view_dir,0.0);
    if (u_light_count > 5) lit += term(u_light_position5,u_light_color5,world,normal,albedo,view_dir,0.0);
    if (u_light_count > 6) lit += term(u_light_position6,u_light_color6,world,normal,albedo,view_dir,0.0);
    if (u_light_count > 7) lit += term(u_light_position7,u_light_color7,world,normal,albedo,view_dir,0.0);
    gl_FragColor = vec4(lit, 1.0);
}
"""


def _receiver_payload():
    """Two upward-facing triangles used only by the 3D lab."""
    vertices = ((-3.5, -1.35, -3.5, 0, 1, 0),
                (3.5, -1.35, 3.5, 0, 1, 0),
                (3.5, -1.35, -3.5, 0, 1, 0),
                (-3.5, -1.35, -3.5, 0, 1, 0),
                (-3.5, -1.35, 3.5, 0, 1, 0),
                (3.5, -1.35, 3.5, 0, 1, 0))
    return b"".join(struct.pack("<6f", *vertex) for vertex in vertices)


RECEIVER_PAYLOAD = _receiver_payload()
RECEIVER_VERTICES = 6
QUAD_PAYLOAD = b"".join(struct.pack("<4f", *vertex) for vertex in
                        ((-1, -1, 0, 0), (1, -1, 1, 0), (1, 1, 1, 1),
                         (-1, -1, 0, 0), (1, 1, 1, 1), (-1, 1, 0, 1)))


class _PipelineGLFunctions:
    """Small Qt-resolved function table for PyQt builds without wrappers."""
    def __init__(self, context):
        factory = ctypes.WINFUNCTYPE if os.name == "nt" else ctypes.CFUNCTYPE
        specs = {
            "glEnable": (None, ctypes.c_uint),
            "glDisable": (None, ctypes.c_uint),
            "glDepthFunc": (None, ctypes.c_uint),
            "glCullFace": (None, ctypes.c_uint),
            "glFrontFace": (None, ctypes.c_uint),
            "glPolygonMode": (None, ctypes.c_uint, ctypes.c_uint),
            "glClear": (None, ctypes.c_uint),
            "glClearColor": (None, ctypes.c_float, ctypes.c_float,
                             ctypes.c_float, ctypes.c_float),
            "glViewport": (None, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int),
            "glDrawArrays": (None, ctypes.c_uint, ctypes.c_int, ctypes.c_int),
            "glActiveTexture": (None, ctypes.c_uint),
            "glBindTexture": (None, ctypes.c_uint, ctypes.c_uint),
            "glTexParameteri": (None, ctypes.c_uint, ctypes.c_uint,
                                ctypes.c_int),
            "glBindFramebuffer": (None, ctypes.c_uint, ctypes.c_uint),
            "glDrawBuffers": (None, ctypes.c_int,
                              ctypes.POINTER(ctypes.c_uint)),
        }
        for name, signature in specs.items():
            address = context.getProcAddress(name.encode("ascii"))
            pointer = int(address) if address is not None else 0
            if not pointer:
                raise RuntimeError(f"OpenGL function is unavailable: {name}")
            setattr(self, name, factory(signature[0], *signature[1:])(pointer))

    def initializeOpenGLFunctions(self):
        return True


class Pipeline3DViewport(QOpenGLWidget):
    state_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 360)
        self.setFocusPolicy(Qt.StrongFocus)
        self.config = Pipeline3DConfig()
        self.mesh = cube_mesh()
        self.program = None
        self.gbuffer_program = None
        self.deferred_program = None
        self.buffer = None
        self.vertex_array = None
        self.quad_buffer = None
        self.quad_vertex_array = None
        self.functions = None
        self.upload_pending = True
        self.upload_count = 0
        self.draw_calls = 0
        self.last_draw_ms = 0.0
        self.last_error = ""
        self._last_mouse = None
        self.shadow_target = None
        self.normal_target = None
        self.depth_target = None
        self.comparison_target = None
        self.comparison_targets = {}
        self.gbuffer_target = None
        self.shadow_passes = 0
        self.attachment_passes = 0
        self.gbuffer_passes = 0
        self.lighting_passes = 0

    def set_mesh(self, mesh):
        self.mesh = mesh
        self.upload_pending = True
        self.update(); self.state_changed.emit()

    def set_config(self, config):
        self.config = config
        self.update(); self.state_changed.emit()

    def initializeGL(self):
        try:
            context = QOpenGLContext.currentContext()
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
            program.bindAttributeLocation("a_position", 0)
            program.bindAttributeLocation("a_normal", 1)
            if not program.link():
                raise RuntimeError(program.log())
            gbuffer_program = QOpenGLShaderProgram()
            if not gbuffer_program.addShaderFromSourceCode(QOpenGLShader.Vertex, VERTEX_SHADER):
                raise RuntimeError(gbuffer_program.log())
            if not gbuffer_program.addShaderFromSourceCode(
                    QOpenGLShader.Fragment, GBUFFER_FRAGMENT_SHADER):
                raise RuntimeError(gbuffer_program.log())
            gbuffer_program.bindAttributeLocation("a_position", 0)
            gbuffer_program.bindAttributeLocation("a_normal", 1)
            if not gbuffer_program.link():
                raise RuntimeError(gbuffer_program.log())
            deferred_program = QOpenGLShaderProgram()
            if not deferred_program.addShaderFromSourceCode(
                    QOpenGLShader.Vertex, QUAD_VERTEX_SHADER):
                raise RuntimeError(deferred_program.log())
            if not deferred_program.addShaderFromSourceCode(
                    QOpenGLShader.Fragment, DEFERRED_FRAGMENT_SHADER):
                raise RuntimeError(deferred_program.log())
            deferred_program.bindAttributeLocation("a_position", 0)
            deferred_program.bindAttributeLocation("a_uv", 1)
            if not deferred_program.link():
                raise RuntimeError(deferred_program.log())
            buffer = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
            vertex_array = QOpenGLVertexArrayObject()
            quad_buffer = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
            quad_vertex_array = QOpenGLVertexArrayObject()
            if (not buffer.create() or not vertex_array.create()
                    or not quad_buffer.create() or not quad_vertex_array.create()):
                raise RuntimeError("无法创建 3D VAO/VBO")
            vertex_array.bind(); buffer.bind()
            buffer.setUsagePattern(QOpenGLBuffer.DynamicDraw)
            program.bind()
            for name, offset in (("a_position", 0), ("a_normal", 12)):
                location = program.attributeLocation(name)
                program.enableAttributeArray(location)
                program.setAttributeBuffer(location, GL_FLOAT, offset, 3,
                                           MESH_VERTEX_STRIDE)
            program.release(); buffer.release(); vertex_array.release()
            quad_vertex_array.bind(); quad_buffer.bind()
            quad_buffer.setUsagePattern(QOpenGLBuffer.StaticDraw)
            quad_buffer.allocate(QUAD_PAYLOAD, len(QUAD_PAYLOAD))
            deferred_program.bind()
            for name, offset in (("a_position", 0), ("a_uv", 8)):
                location = deferred_program.attributeLocation(name)
                deferred_program.enableAttributeArray(location)
                deferred_program.setAttributeBuffer(location, GL_FLOAT, offset, 2, 16)
            deferred_program.release(); quad_buffer.release(); quad_vertex_array.release()
            self.program, self.buffer, self.vertex_array = program, buffer, vertex_array
            self.gbuffer_program, self.deferred_program = gbuffer_program, deferred_program
            self.quad_buffer, self.quad_vertex_array = quad_buffer, quad_vertex_array
            self.shadow_target = self.normal_target = self.depth_target = None
            self.comparison_target = None
            self.comparison_targets = {}
            self.gbuffer_target = None
            self.upload_pending = True
            self.last_error = ""
        except Exception as error:
            self.last_error = str(error)

    def _upload(self):
        if self.buffer is None or self.vertex_array is None:
            return False
        payload = self.mesh.payload + RECEIVER_PAYLOAD
        self.vertex_array.bind(); self.buffer.bind()
        self.buffer.allocate(payload, len(payload))
        self.buffer.release(); self.vertex_array.release()
        self.upload_pending = False
        self.upload_count += 1
        return True

    def _target(self, kind, width, height):
        attribute = f"{kind}_target"
        target = getattr(self, attribute)
        if target is not None and target.size().width() == width and target.size().height() == height:
            return target
        target = None
        format_ = QOpenGLFramebufferObjectFormat()
        format_.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
        format_.setInternalTextureFormat(GL_RGBA8)
        candidate = QOpenGLFramebufferObject(width, height, format_)
        if not candidate.isValid():
            raise RuntimeError(f"无法创建 {kind} framebuffer {width}x{height}")
        setattr(self, attribute, candidate)
        return candidate

    def _gbuffer(self, width, height):
        target = self.gbuffer_target
        if (target is not None and target.size().width() == width
                and target.size().height() == height):
            return target
        format_ = QOpenGLFramebufferObjectFormat()
        format_.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
        format_.setInternalTextureFormat(GL_RGBA16F)
        target = QOpenGLFramebufferObject(width, height, format_)
        target.addColorAttachment(width, height, GL_RGBA16F)
        target.addColorAttachment(width, height, GL_RGBA8)
        if not target.isValid() or len(target.textures()) != 3:
            raise RuntimeError("无法创建 3-attachment G-buffer")
        self.gbuffer_target = target
        return target

    def _set_common_uniforms(self, model, view, projection, mode):
        _, _, light_vp = light_matrices(self.config)
        camera = camera_position(self.config)
        program = self.program
        program.setUniformValue("u_model", model)
        program.setUniformValue("u_view", view)
        program.setUniformValue("u_projection", projection)
        program.setUniformValue("u_light_view_projection", light_vp)
        program.setUniformValue("u_mode", mode)
        program.setUniformValue("u_shadow_enabled", 1 if self.config.shadows else 0)
        program.setUniformValue("u_pcf_radius", self.config.pcf_radius)
        program.setUniformValue("u_shadow_bias", self.config.shadow_bias)
        program.setUniformValue("u_shadow_texel", 1.0 / self.config.shadow_resolution)
        program.setUniformValue("u_ambient", self.config.ambient)
        program.setUniformValue("u_diffuse", self.config.diffuse)
        program.setUniformValue("u_specular", self.config.specular)
        program.setUniformValue("u_shininess", self.config.shininess)
        program.setUniformValue("u_light_position", QVector3D(
            self.config.light_x, self.config.light_y, self.config.light_z))
        program.setUniformValue("u_camera_position", camera)
        program.setUniformValue("u_shadow_map", 0)
        self._set_light_uniforms(program)

    def _set_light_uniforms(self, program):
        lights = scene_lights(self.config)
        program.setUniformValue("u_light_count", len(lights))
        for index in range(8):
            position, color = (lights[index] if index < len(lights)
                               else ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))
            program.setUniformValue(f"u_light_position{index}", QVector3D(*position))
            program.setUniformValue(f"u_light_color{index}", QVector3D(*color))

    def _draw_scene(self, view, projection, mode):
        model, _, _ = pipeline_matrices(
            self.config, self.width() / max(1.0, self.height()))
        self._set_common_uniforms(model, view, projection, mode)
        self.program.setUniformValue("u_base_color", QVector3D(0.16, 0.58, 0.92))
        self.functions.glDrawArrays(GL_TRIANGLES, 0, self.mesh.vertex_count)
        identity = QMatrix4x4()
        self.program.setUniformValue("u_model", identity)
        self.program.setUniformValue("u_base_color", QVector3D(0.38, 0.42, 0.48))
        self.functions.glDrawArrays(GL_TRIANGLES, self.mesh.vertex_count,
                                    RECEIVER_VERTICES)

    def _render_shadow_pass(self):
        resolution = self.config.shadow_resolution
        target = self._target("shadow", resolution, resolution)
        target.bind()
        self.functions.glViewport(0, 0, resolution, resolution)
        self.functions.glEnable(GL_DEPTH_TEST); self.functions.glDepthFunc(GL_LESS)
        self.functions.glEnable(GL_CULL_FACE); self.functions.glCullFace(GL_BACK)
        self.functions.glClearColor(1.0, 1.0, 1.0, 1.0)
        self.functions.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        light_view, light_projection, _ = light_matrices(self.config)
        self.vertex_array.bind(); self.buffer.bind(); self.program.bind()
        self._draw_scene(light_view, light_projection, 4)
        self.program.release(); self.buffer.release(); self.vertex_array.release()
        target.release(); self.shadow_passes += 1
        return target

    def _render_debug_target(self, kind):
        width, height = max(1, self.width()), max(1, self.height())
        target = self._target(kind, width, height)
        target.bind(); self.functions.glViewport(0, 0, width, height)
        self.functions.glEnable(GL_DEPTH_TEST); self.functions.glDepthFunc(GL_LESS)
        self.functions.glClearColor(0.055, 0.075, 0.105, 1.0)
        self.functions.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        _, view, projection = pipeline_matrices(self.config, width / max(1.0, height))
        self.vertex_array.bind(); self.buffer.bind(); self.program.bind()
        self._draw_scene(view, projection, 2 if kind == "normal" else 3)
        self.program.release(); self.buffer.release(); self.vertex_array.release()
        target.release()
        return target

    def render_comparison(self, kind, resolution, cull_back_faces=True,
                          sample_count=1):
        if kind not in ("normal", "depth"):
            raise ValueError("comparison kind must be normal or depth")
        try:
            self.makeCurrent()
            if self.upload_pending and not self._upload():
                return None
            resolution = int(resolution)
            sample_count = int(sample_count)
            if sample_count not in (1, 4):
                raise ValueError("comparison samples must be 1 or 4")
            target_key = (resolution, sample_count)
            target = self.comparison_targets.get(target_key)
            if target is None:
                format_ = QOpenGLFramebufferObjectFormat()
                format_.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
                format_.setInternalTextureFormat(GL_RGBA8)
                format_.setSamples(sample_count if sample_count > 1 else 0)
                target = QOpenGLFramebufferObject(resolution, resolution, format_)
                if not target.isValid():
                    raise RuntimeError(
                        f"无法创建 comparison framebuffer {resolution}x{resolution}")
                # Keep one FBO per supported size for the lifetime of this context.
                # Replacing the sole PyQt wrapper during an active widget render can
                # destroy the old GL object at an unsafe point on some drivers.
                self.comparison_targets[target_key] = target
            self.comparison_target = target
            target.bind()
            self.functions.glViewport(0, 0, resolution, resolution)
            self.functions.glEnable(GL_DEPTH_TEST); self.functions.glDepthFunc(GL_LESS)
            if cull_back_faces:
                self.functions.glEnable(GL_CULL_FACE)
                self.functions.glCullFace(GL_BACK); self.functions.glFrontFace(GL_CCW)
            else:
                self.functions.glDisable(GL_CULL_FACE)
            self.functions.glClearColor(0.055, 0.075, 0.105, 1.0)
            self.functions.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            _, view, projection = pipeline_matrices(self.config, 1.0)
            self.vertex_array.bind(); self.buffer.bind(); self.program.bind()
            self._draw_scene(view, projection, 2 if kind == "normal" else 3)
            self.program.release(); self.buffer.release(); self.vertex_array.release()
            target.release()
            image = target.toImage()
            self.doneCurrent(); return image
        except Exception as error:
            self.last_error = f"comparison: {error}"
            try: self.doneCurrent()
            except Exception: pass
            return None

    def _render_gbuffer(self):
        width, height = max(1, self.width()), max(1, self.height())
        target = self._gbuffer(width, height)
        target.bind(); self.functions.glViewport(0, 0, width, height)
        attachments = (ctypes.c_uint * 3)(GL_COLOR_ATTACHMENT0,
                                           GL_COLOR_ATTACHMENT0 + 1,
                                           GL_COLOR_ATTACHMENT0 + 2)
        self.functions.glDrawBuffers(3, attachments)
        self.functions.glEnable(GL_DEPTH_TEST); self.functions.glDepthFunc(GL_LESS)
        if self.config.cull_back_faces:
            self.functions.glEnable(GL_CULL_FACE)
        else:
            self.functions.glDisable(GL_CULL_FACE)
        self.functions.glClearColor(0.0, 0.0, 0.0, 0.0)
        self.functions.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        model, view, projection = pipeline_matrices(
            self.config, width / max(1.0, height))
        program = self.gbuffer_program
        self.vertex_array.bind(); self.buffer.bind(); program.bind()
        _, _, light_vp = light_matrices(self.config)
        program.setUniformValue("u_view", view)
        program.setUniformValue("u_projection", projection)
        program.setUniformValue("u_light_view_projection", light_vp)
        program.setUniformValue("u_model", model)
        program.setUniformValue("u_base_color", QVector3D(0.16, 0.58, 0.92))
        self.functions.glDrawArrays(GL_TRIANGLES, 0, self.mesh.vertex_count)
        program.setUniformValue("u_model", QMatrix4x4())
        program.setUniformValue("u_base_color", QVector3D(0.38, 0.42, 0.48))
        self.functions.glDrawArrays(GL_TRIANGLES, self.mesh.vertex_count,
                                    RECEIVER_VERTICES)
        program.release(); self.buffer.release(); self.vertex_array.release()
        target.release(); self.gbuffer_passes += 1
        return target

    def _render_deferred_lighting(self, target, shadow_target):
        self.functions.glBindFramebuffer(
            GL_FRAMEBUFFER, self.defaultFramebufferObject())
        width, height = max(1, self.width()), max(1, self.height())
        self.functions.glViewport(0, 0, width, height)
        self.functions.glDisable(GL_DEPTH_TEST); self.functions.glDisable(GL_CULL_FACE)
        self.functions.glClearColor(0.055, 0.075, 0.105, 1.0)
        self.functions.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        textures = target.textures()
        for unit, texture in enumerate(textures):
            self.functions.glActiveTexture(GL_TEXTURE0 + unit)
            self.functions.glBindTexture(GL_TEXTURE_2D, texture)
        self.functions.glActiveTexture(GL_TEXTURE0 + 3)
        self.functions.glBindTexture(
            GL_TEXTURE_2D, shadow_target.texture() if shadow_target else 0)
        program = self.deferred_program
        self.quad_vertex_array.bind(); self.quad_buffer.bind(); program.bind()
        program.setUniformValue("u_g_position", 0)
        program.setUniformValue("u_g_normal", 1)
        program.setUniformValue("u_g_albedo", 2)
        program.setUniformValue("u_shadow_map", 3)
        _, _, light_vp = light_matrices(self.config)
        program.setUniformValue("u_light_view_projection", light_vp)
        program.setUniformValue("u_camera_position", camera_position(self.config))
        program.setUniformValue("u_ambient", self.config.ambient)
        program.setUniformValue("u_diffuse", self.config.diffuse)
        program.setUniformValue("u_specular", self.config.specular)
        program.setUniformValue("u_shininess", self.config.shininess)
        program.setUniformValue("u_shadow_enabled", 1 if self.config.shadows else 0)
        program.setUniformValue("u_shadow_bias", self.config.shadow_bias)
        program.setUniformValue("u_shadow_texel", 1.0 / self.config.shadow_resolution)
        program.setUniformValue("u_pcf_radius", self.config.pcf_radius)
        self._set_light_uniforms(program)
        self.functions.glDrawArrays(GL_TRIANGLES, 0, 6)
        program.release(); self.quad_buffer.release(); self.quad_vertex_array.release()
        for unit in range(4):
            self.functions.glActiveTexture(GL_TEXTURE0 + unit)
            self.functions.glBindTexture(GL_TEXTURE_2D, 0)
        self.functions.glActiveTexture(GL_TEXTURE0)
        self.lighting_passes += 1

    def render_attachment(self, kind):
        if kind not in ("normal", "depth", "shadow",
                        "g_position", "g_normal", "g_albedo"):
            raise ValueError("invalid 3D attachment")
        try:
            self.makeCurrent()
            if self.upload_pending and not self._upload():
                return None
            if kind.startswith("g_"):
                target = self._render_gbuffer()
                index = {"g_position": 0, "g_normal": 1, "g_albedo": 2}[kind]
                image = target.toImage(True, index)
            else:
                target = (self._render_shadow_pass() if kind == "shadow"
                          else self._render_debug_target(kind))
                image = target.toImage()
            self.attachment_passes += 1
            self.doneCurrent(); self.state_changed.emit()
            return image
        except Exception as error:
            self.last_error = f"attachment: {error}"
            try: self.doneCurrent()
            except Exception: pass
            self.state_changed.emit(); return None

    def resizeGL(self, width, height):
        if self.functions:
            self.functions.glViewport(0, 0, max(1, width), max(1, height))

    def paintGL(self):
        started = time.perf_counter()
        stage = "clear"
        try:
            if self.functions is None:
                return
            if self.program is None or not self.mesh.vertices:
                return
            stage = "upload"
            if self.upload_pending and not self._upload():
                return
            stage = "shadow-pass"
            shadow_required = self.config.shadows or self.config.view_mode == "shadow_map"
            shadow_target = None
            if shadow_required:
                self.functions.glActiveTexture(GL_TEXTURE0)
                self.functions.glBindTexture(GL_TEXTURE_2D, 0)
                shadow_target = self._render_shadow_pass()
            if (self.config.render_path == "deferred"
                    and self.config.view_mode == "final"):
                stage = "gbuffer-pass"
                if hasattr(self.functions, "glPolygonMode"):
                    self.functions.glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
                gbuffer = self._render_gbuffer()
                stage = "deferred-lighting"
                self._render_deferred_lighting(gbuffer, shadow_target)
                self.draw_calls = 5 if shadow_required else 3
                self.last_error = ""
                return
            stage = "default-target"
            self.functions.glBindFramebuffer(
                GL_FRAMEBUFFER, self.defaultFramebufferObject())
            self.functions.glViewport(0, 0, max(1, self.width()), max(1, self.height()))
            self.functions.glClearColor(0.055, 0.075, 0.105, 1.0)
            self.functions.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            stage = "raster-state"
            if self.config.depth_test:
                self.functions.glEnable(GL_DEPTH_TEST)
                self.functions.glDepthFunc(GL_LESS)
            else:
                self.functions.glDisable(GL_DEPTH_TEST)
            if self.config.cull_back_faces:
                self.functions.glEnable(GL_CULL_FACE)
                self.functions.glCullFace(GL_BACK); self.functions.glFrontFace(GL_CCW)
            else:
                self.functions.glDisable(GL_CULL_FACE)
            wireframe = self.config.view_mode == "wireframe"
            if hasattr(self.functions, "glPolygonMode"):
                self.functions.glPolygonMode(GL_FRONT_AND_BACK, GL_LINE if wireframe else GL_FILL)
            model, view, projection = pipeline_matrices(
                self.config, self.width() / max(1.0, self.height()))
            stage = "bind"
            self.vertex_array.bind(); self.buffer.bind(); self.program.bind()
            if shadow_target is not None:
                self.functions.glActiveTexture(GL_TEXTURE0)
                self.functions.glBindTexture(GL_TEXTURE_2D, shadow_target.texture())
            stage = "uniforms"
            mode = {"final": 0, "wireframe": 1, "normals": 2, "depth": 3,
                    "shadow_map": 5}[
                self.config.view_mode]
            stage = "draw"
            self._draw_scene(view, projection, mode)
            self.program.release(); self.buffer.release(); self.vertex_array.release()
            self.functions.glBindTexture(GL_TEXTURE_2D, 0)
            if hasattr(self.functions, "glPolygonMode"):
                self.functions.glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
            self.draw_calls = 4 if shadow_required else 2
            self.last_error = ""
        except Exception as error:
            self.last_error = f"{stage}: {error}"
            self.draw_calls = 0
        finally:
            self.last_draw_ms = (time.perf_counter() - started) * 1000.0

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._last_mouse = event.pos(); event.accept(); return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._last_mouse is not None and event.buttons() & Qt.LeftButton:
            delta = event.pos() - self._last_mouse; self._last_mouse = event.pos()
            self.set_config(self.config.changed(
                camera_yaw=self.config.camera_yaw + delta.x() * 0.45,
                camera_pitch=max(-85.0, min(85.0,
                    self.config.camera_pitch + delta.y() * 0.45))))
            event.accept(); return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._last_mouse = None; super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        factor = 0.88 if event.angleDelta().y() > 0 else 1.14
        self.set_config(self.config.changed(
            camera_distance=max(1.2, min(30.0,
                self.config.camera_distance * factor))))
        event.accept()

    def runtime_state(self):
        context = self.context()
        version = context.format() if context else None
        return {
            "context_valid": bool(self.isValid() and context),
            "context_version": (f"{version.majorVersion()}.{version.minorVersion()}"
                                if version else "—"),
            "vertices": self.mesh.vertex_count,
            "triangles": self.mesh.triangle_count,
            "vbo_bytes": len(self.mesh.payload),
            "upload_count": self.upload_count,
            "draw_calls": self.draw_calls,
            "draw_ms": self.last_draw_ms,
            "shadow_passes": self.shadow_passes,
            "attachment_passes": self.attachment_passes,
            "shadow_size": (self.config.shadow_resolution,
                            self.config.shadow_resolution),
            "shadow_bytes": self.config.shadow_resolution ** 2 * 7,
            "gbuffer_passes": self.gbuffer_passes,
            "lighting_passes": self.lighting_passes,
            "gbuffer_size": (max(1, self.width()), max(1, self.height())),
            "gbuffer_bytes": max(1, self.width()) * max(1, self.height()) * 24,
            "deferred_frame_bytes": max(1, self.width()) * max(1, self.height()) * 40,
            "error": self.last_error or self.mesh.error,
        }


class Pipeline3DPanel(QWidget):
    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.config = Pipeline3DConfig()
        self.source_shape_id = ""
        self.source_warning = ""
        self.software_result = None
        self.software_gpu_image = None
        self.software_gpu_buffer = b""
        self.software_comparison = None
        self.software_stale = True
        self._updating = False
        self._build_ui()
        canvas.selection_changed.connect(self._document_changed)
        canvas.canvas_changed.connect(self._document_changed)
        self._rebuild_mesh(); self.refresh()

    def _spin(self, low, high, value, step=1.0, decimals=1):
        control = QDoubleSpinBox(); control.setRange(low, high)
        control.setValue(value); control.setSingleStep(step); control.setDecimals(decimals)
        return control

    def _scroll_tab(self, tabs, title):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget(); content.setObjectName(f"pipeline3d_{title}_content")
        page_layout = QVBoxLayout(content)
        page_layout.setContentsMargins(8, 8, 8, 8)
        page_layout.setSpacing(8)
        scroll.setWidget(content)
        tabs.addTab(scroll, title)
        return page_layout

    def _build_ui(self):
        layout = QVBoxLayout(self)
        intro = QLabel("二维选择 → C++ extrusion mesh → Object/World/View/Clip/NDC/Screen → OpenGL raster。左键旋转相机，滚轮缩放。")
        intro.setWordWrap(True); layout.addWidget(intro)
        splitter = QSplitter(Qt.Horizontal); layout.addWidget(splitter, 1)
        splitter.setObjectName("pipeline3d_splitter")
        splitter.setChildrenCollapsible(False)
        self.viewport = Pipeline3DViewport(); splitter.addWidget(self.viewport)
        self.viewport.state_changed.connect(self.refresh)
        self.property_tabs = QTabWidget()
        self.property_tabs.setObjectName("pipeline3d_property_tabs")
        self.property_tabs.setDocumentMode(True)
        self.property_tabs.setMinimumWidth(360)
        self.property_tabs.tabBar().setExpanding(False)
        self.property_tabs.tabBar().setUsesScrollButtons(True)
        self.property_tabs.tabBar().setElideMode(Qt.ElideRight)
        splitter.addWidget(self.property_tabs)
        splitter.setStretchFactor(0, 3); splitter.setStretchFactor(1, 2)
        splitter.setSizes([760, 420])
        self.scene_page_layout = self._scroll_tab(self.property_tabs, "场景/相机")
        self.lighting_page_layout = self._scroll_tab(self.property_tabs, "光照/阴影")
        self.attachment_page_layout = self._scroll_tab(self.property_tabs, "附件/G-buffer")
        self.diagnostics_page_layout = self._scroll_tab(self.property_tabs, "追踪/统计")
        self.software_page_layout = self._scroll_tab(self.property_tabs, "CPU/OpenGL")

        group = QGroupBox("Mesh / Pipeline")
        form = QFormLayout(group)
        self.source_combo = QComboBox(); self.source_combo.addItem("程序化立方体", "cube")
        self.source_combo.addItem("当前选中二维图元", "selection")
        self.depth_spin = self._spin(0.05, 4.0, 0.7, 0.05, 2)
        self.mode_combo = QComboBox()
        for label, value in VIEW_MODES: self.mode_combo.addItem(label, value)
        self.depth_check = QCheckBox("启用 Depth Test"); self.depth_check.setChecked(True)
        self.cull_check = QCheckBox("启用 Back-face Culling"); self.cull_check.setChecked(True)
        self.fov_spin = self._spin(10, 120, 45, 1, 1)
        self.near_spin = self._spin(0.01, 10, 0.1, 0.05, 2)
        self.far_spin = self._spin(2, 500, 100, 1, 1)
        self.rx_spin = self._spin(-360, 360, -12)
        self.ry_spin = self._spin(-360, 360, 28)
        self.rz_spin = self._spin(-360, 360, 0)
        form.addRow("来源", self.source_combo); form.addRow("挤出厚度", self.depth_spin)
        form.addRow("显示模式", self.mode_combo); form.addRow(self.depth_check)
        form.addRow(self.cull_check); form.addRow("FOV", self.fov_spin)
        form.addRow("Near", self.near_spin); form.addRow("Far", self.far_spin)
        form.addRow("模型旋转 X", self.rx_spin); form.addRow("模型旋转 Y", self.ry_spin)
        form.addRow("模型旋转 Z", self.rz_spin)
        reset = QPushButton("重置相机/模型"); reset.clicked.connect(self._reset)
        form.addRow(reset); self.scene_page_layout.addWidget(group)
        self.scene_page_layout.addStretch(1)

        lighting_group = QGroupBox("Blinn-Phong / Shadow Mapping")
        lighting_form = QFormLayout(lighting_group)
        self.render_path_combo = QComboBox()
        self.render_path_combo.addItem("Forward Shading", "forward")
        self.render_path_combo.addItem("Deferred Shading", "deferred")
        self.light_count_combo = QComboBox()
        for count in (1, 4, 8):
            self.light_count_combo.addItem(f"{count} lights", count)
        self.light_x_spin = self._spin(-10, 10, 2.8, 0.2, 2)
        self.light_y_spin = self._spin(0.2, 12, 4.2, 0.2, 2)
        self.light_z_spin = self._spin(-10, 10, 3.0, 0.2, 2)
        self.ambient_spin = self._spin(0, 2, 0.16, 0.02, 2)
        self.diffuse_spin = self._spin(0, 2, 0.82, 0.02, 2)
        self.specular_spin = self._spin(0, 2, 0.55, 0.05, 2)
        self.shininess_spin = self._spin(1, 256, 48, 4, 0)
        self.shadow_check = QCheckBox("启用 Shadow Map"); self.shadow_check.setChecked(True)
        self.shadow_resolution_combo = QComboBox()
        for resolution in (256, 512, 1024):
            self.shadow_resolution_combo.addItem(f"{resolution} × {resolution}", resolution)
        self.bias_spin = self._spin(0, 0.05, 0.003, 0.0005, 4)
        self.pcf_combo = QComboBox()
        self.pcf_combo.addItem("Hard (1 sample)", 0)
        self.pcf_combo.addItem("3×3 PCF", 1)
        self.pcf_combo.addItem("5×5 PCF", 2)
        for label, control in (("Render path", self.render_path_combo),
                               ("Light count", self.light_count_combo),
                               ("Light X", self.light_x_spin),
                               ("Light Y", self.light_y_spin),
                               ("Light Z", self.light_z_spin),
                               ("Ambient", self.ambient_spin),
                               ("Diffuse", self.diffuse_spin),
                               ("Specular", self.specular_spin),
                               ("Shininess", self.shininess_spin)):
            lighting_form.addRow(label, control)
        lighting_form.addRow(self.shadow_check)
        lighting_form.addRow("Shadow resolution", self.shadow_resolution_combo)
        lighting_form.addRow("Depth bias", self.bias_spin)
        lighting_form.addRow("Filter", self.pcf_combo)
        self.path_note = QLabel(); self.path_note.setWordWrap(True)
        lighting_form.addRow(self.path_note)
        self.lighting_page_layout.addWidget(lighting_group)
        self.lighting_page_layout.addStretch(1)

        attachment_group = QGroupBox("真实 OpenGL 附件（手动读取）")
        attachment_layout = QVBoxLayout(attachment_group)
        self.attachment_combo = QComboBox()
        for label, value in ATTACHMENT_MODES:
            self.attachment_combo.addItem(label, value)
        attachment_layout.addWidget(self.attachment_combo)
        attachment_button = QPushButton("生成附件预览")
        attachment_button.clicked.connect(self._preview_attachment)
        attachment_layout.addWidget(attachment_button)
        self.attachment_preview = QLabel("选择附件后手动生成；不会写入二维文档")
        self.attachment_preview.setAlignment(Qt.AlignCenter)
        self.attachment_preview.setMinimumHeight(160)
        self.attachment_preview.setStyleSheet("background:#20252b; color:#d7dde5")
        attachment_layout.addWidget(self.attachment_preview)
        self.attachment_page_layout.addWidget(attachment_group)
        self.attachment_page_layout.addStretch(1)

        trace_group = QGroupBox("顶点管线追踪")
        trace_layout = QVBoxLayout(trace_group)
        self.vertex_spin = QSpinBox(); self.vertex_spin.setMinimum(0)
        trace_layout.addWidget(self.vertex_spin)
        self.trace_table = QTableWidget(0, 2)
        self.trace_table.setMinimumHeight(250)
        self.trace_table.setHorizontalHeaderLabels(["阶段", "vec4"])
        self.trace_table.horizontalHeader().setStretchLastSection(True)
        trace_layout.addWidget(self.trace_table)
        self.diagnostics_page_layout.addWidget(trace_group)
        self.state_label = QLabel(); self.state_label.setWordWrap(True)
        self.state_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        state_group = QGroupBox("运行统计 / 资源状态")
        state_layout = QVBoxLayout(state_group); state_layout.addWidget(self.state_label)
        self.diagnostics_page_layout.addWidget(state_group)
        self.diagnostics_page_layout.addStretch(1)

        software_group = QGroupBox("C++ Software Rasterizer")
        software_layout = QVBoxLayout(software_group)
        software_form = QFormLayout()
        self.software_resolution_combo = QComboBox()
        for resolution in (128, 256, 512):
            self.software_resolution_combo.addItem(f"{resolution} × {resolution}", resolution)
        self.software_attachment_combo = QComboBox()
        self.software_attachment_combo.addItem("Normal RGB attributes", "color")
        self.software_attachment_combo.addItem("Barycentric RGB", "barycentric")
        self.software_attachment_combo.addItem("Depth", "depth")
        self.software_compare_combo = QComboBox()
        self.software_compare_combo.addItem("Normal RGB", "normal")
        self.software_compare_combo.addItem("Depth", "depth")
        self.software_perspective_check = QCheckBox("Perspective-correct interpolation")
        self.software_perspective_check.setChecked(True)
        self.software_cull_check = QCheckBox("Back-face culling")
        self.software_cull_check.setChecked(True)
        self.software_clip_check = QCheckBox("Homogeneous clip volume (±w)")
        self.software_clip_check.setChecked(True)
        self.software_samples_combo = QComboBox()
        self.software_samples_combo.addItem("1× center sample", 1)
        self.software_samples_combo.addItem("4× rotated-grid MSAA", 4)
        software_form.addRow("Resolution", self.software_resolution_combo)
        software_form.addRow("Samples", self.software_samples_combo)
        software_form.addRow("CPU attachment", self.software_attachment_combo)
        software_form.addRow("CPU/GPU 指标", self.software_compare_combo)
        software_form.addRow(self.software_perspective_check)
        software_form.addRow(self.software_cull_check)
        software_form.addRow(self.software_clip_check)
        software_layout.addLayout(software_form)
        run_software = QPushButton("运行 CPU + 固定 GPU 对照")
        run_software.clicked.connect(self._run_software_rasterizer)
        software_layout.addWidget(run_software)
        software_layout.addWidget(QLabel("CPU attachment"))
        self.software_preview = QLabel("点击运行；同一次计算生成 Color / Barycentric / Depth")
        self.software_preview.setAlignment(Qt.AlignCenter)
        self.software_preview.setMinimumHeight(220)
        self.software_preview.setStyleSheet("background:#20252b; color:#d7dde5")
        software_layout.addWidget(self.software_preview)
        software_layout.addWidget(QLabel("对齐后的 OpenGL comparison attachment"))
        self.software_gpu_preview = QLabel("与 CPU 使用相同尺寸和 Normal/Depth 语义")
        self.software_gpu_preview.setAlignment(Qt.AlignCenter)
        self.software_gpu_preview.setMinimumHeight(220)
        self.software_gpu_preview.setStyleSheet("background:#20252b; color:#d7dde5")
        software_layout.addWidget(self.software_gpu_preview)
        software_layout.addWidget(QLabel("Difference heatmap：绿/黑=小差异，洋红=仅 CPU，黄色=仅 GPU"))
        self.software_heatmap_preview = QLabel("运行后生成量化差异")
        self.software_heatmap_preview.setAlignment(Qt.AlignCenter)
        self.software_heatmap_preview.setMinimumHeight(220)
        self.software_heatmap_preview.setStyleSheet("background:#20252b; color:#d7dde5")
        software_layout.addWidget(self.software_heatmap_preview)
        probe_form = QFormLayout()
        self.software_probe_x = QSpinBox(); self.software_probe_x.setMinimum(0)
        self.software_probe_y = QSpinBox(); self.software_probe_y.setMinimum(0)
        probe_form.addRow("Probe X", self.software_probe_x)
        probe_form.addRow("Probe Y", self.software_probe_y)
        software_layout.addLayout(probe_form)
        self.software_probe_label = QLabel("像素探针：运行后选择坐标")
        self.software_probe_label.setWordWrap(True)
        self.software_probe_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        software_layout.addWidget(self.software_probe_label)
        self.software_status = QLabel("CPU raster 不写入二维文档或撤销历史")
        self.software_status.setWordWrap(True)
        self.software_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        software_layout.addWidget(self.software_status)
        self.software_page_layout.addWidget(software_group)
        self.software_page_layout.addStretch(1)
        self.software_attachment_combo.currentIndexChanged.connect(
            self._update_software_preview)
        self.software_compare_combo.currentIndexChanged.connect(
            self._mark_software_stale)
        self.software_resolution_combo.currentIndexChanged.connect(
            self._mark_software_stale)
        self.software_perspective_check.toggled.connect(self._mark_software_stale)
        self.software_cull_check.toggled.connect(self._mark_software_stale)
        self.software_clip_check.toggled.connect(self._mark_software_stale)
        self.software_samples_combo.currentIndexChanged.connect(
            self._mark_software_stale)
        self.software_probe_x.valueChanged.connect(self._update_software_probe)
        self.software_probe_y.valueChanged.connect(self._update_software_probe)
        for control in (self.source_combo, self.depth_spin, self.mode_combo,
                        self.depth_check, self.cull_check, self.fov_spin,
                        self.near_spin, self.far_spin, self.rx_spin,
                        self.ry_spin, self.rz_spin, self.vertex_spin,
                        self.light_x_spin, self.light_y_spin, self.light_z_spin,
                        self.ambient_spin, self.diffuse_spin, self.specular_spin,
                        self.shininess_spin, self.shadow_check,
                        self.shadow_resolution_combo, self.bias_spin,
                        self.pcf_combo, self.render_path_combo,
                        self.light_count_combo):
            signal = (control.toggled if isinstance(control, QCheckBox)
                      else control.currentIndexChanged if isinstance(control, QComboBox)
                      else control.valueChanged)
            signal.connect(self._controls_changed)

    def _mark_software_stale(self, *args):
        self.software_stale = True
        if self.software_result is not None:
            self.software_status.setText(
                "场景或 CPU 参数已变化；当前预览是上一次结果，请重新运行。")

    @staticmethod
    def _rgba_image(buffer, width, height):
        return QImage(buffer, width, height, width * 4,
                      QImage.Format_RGBA8888).copy()

    @staticmethod
    def _show_image(label, image):
        if image is None or image.isNull():
            label.setPixmap(QPixmap()); label.setText("图像不可用"); return
        label.setText("")
        label.setPixmap(QPixmap.fromImage(image).scaled(
            label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _run_software_rasterizer(self):
        resolution = self.software_resolution_combo.currentData()
        sample_count = self.software_samples_combo.currentData()
        revision = self.canvas.render_revision
        history = self.canvas.history_manager.current_index
        try:
            vertices = raster_input_vertices(
                self.viewport.mesh.vertices, self.config, resolution, resolution)
            self.software_result = software_rasterize(
                vertices, resolution, resolution,
                self.software_perspective_check.isChecked(),
                self.software_cull_check.isChecked(),
                self.software_clip_check.isChecked(), sample_count)
            self.software_stale = False
            self._update_software_preview()
            compare_kind = self.software_compare_combo.currentData()
            cpu_buffer = (self.software_result.color if compare_kind == "normal"
                          else self.software_result.depth)
            self.software_gpu_image = self.viewport.render_comparison(
                compare_kind, resolution, self.software_cull_check.isChecked(),
                sample_count)
            if self.software_gpu_image is None or self.software_gpu_image.isNull():
                raise RuntimeError("GPU comparison attachment 不可用")
            converted = self.software_gpu_image.convertToFormat(QImage.Format_RGBA8888)
            pointer = converted.bits(); pointer.setsize(converted.byteCount())
            self.software_gpu_buffer = bytes(pointer)
            self.software_gpu_image = converted.copy()
            self.software_comparison = compare_rgba(
                cpu_buffer, self.software_gpu_buffer, resolution, resolution)
            self._show_image(self.software_gpu_preview, self.software_gpu_image)
            self._show_image(self.software_heatmap_preview, self._rgba_image(
                self.software_comparison.heatmap, resolution, resolution))
            for control in (self.software_probe_x, self.software_probe_y):
                control.blockSignals(True)
                control.setMaximum(resolution - 1)
                control.setValue(resolution // 2)
                control.blockSignals(False)
            self._update_software_probe()
            result = self.software_result
            comparison = self.software_comparison
            self.software_status.setText(
                f"Backend {result.backend} · {result.width}×{result.height} · "
                f"MSAA {result.sample_count}× · input/clip/raster triangles "
                f"{result.input_triangles}/{result.clipped_triangles}/"
                f"{result.rasterized_triangles}\n"
                f"covered samples {result.covered_fragments} · depth passed "
                f"{result.depth_passed_fragments} · {result.elapsed_ms:.3f} ms · "
                f"resolved pixels {result.resolved_covered_pixels} · "
                f"attachments {result.buffer_bytes / 1048576:.2f} MiB · "
                f"native workset ≈{result.native_working_set_bytes / 1048576:.1f} MiB\n"
                f"Coverage CPU/GPU {comparison.cpu_covered}/"
                f"{comparison.gpu_covered} · mismatch {comparison.coverage_mismatch} · "
                f"IoU {comparison.coverage_iou:.4f}\n"
                f"RGB MAE {comparison.mae:.3f} · RMSE {comparison.rmse:.3f} · "
                f"max {comparison.max_error}/255"
                + (f"\n回退原因：{result.error}" if result.error else ""))
        except Exception as error:
            self.software_status.setText(f"软件光栅化失败：{error}")
        if (self.canvas.render_revision != revision or
                self.canvas.history_manager.current_index != history):
            self.software_status.setText(
                self.software_status.text() + "\n错误：CPU 实验意外修改了文档状态")

    def _update_software_preview(self, *args):
        result = self.software_result
        if result is None:
            return
        attachment = self.software_attachment_combo.currentData()
        buffer = getattr(result, attachment)
        self._show_image(self.software_preview,
                         self._rgba_image(buffer, result.width, result.height))

    def _update_software_probe(self, *args):
        if self.software_result is None or not self.software_gpu_buffer:
            return
        # Range changes emit valueChanged independently. Clamp both axes so a
        # transient old coordinate can never escape a Qt signal handler.
        x = max(0, min(self.software_probe_x.value(),
                       self.software_result.width - 1))
        y = max(0, min(self.software_probe_y.value(),
                       self.software_result.height - 1))
        try:
            probe = pixel_probe(
                self.software_result, self.software_gpu_buffer, x, y,
                "color" if self.software_compare_combo.currentData() == "normal"
                else "depth")
        except (ValueError, IndexError) as error:
            self.software_probe_label.setText(f"像素探针暂不可用：{error}")
            return
        triangle = ("background" if probe["triangle_id"] is None
                    else str(probe["triangle_id"]))
        self.software_probe_label.setText(
            f"Pixel ({probe['x']}, {probe['y']}) · CPU/GPU covered "
            f"{probe['cpu_covered']}/{probe['gpu_covered']}\n"
            f"CPU {probe['cpu_rgba']} · GPU {probe['gpu_rgba']} · "
            f"|ΔRGB| {probe['absolute_rgb']}\n"
            f"Triangle {triangle} · barycentric "
            f"({probe['barycentric'][0]:.3f}, {probe['barycentric'][1]:.3f}, "
            f"{probe['barycentric'][2]:.3f}) · depth {probe['depth']:.3f}")

    def _preview_attachment(self):
        image = self.viewport.render_attachment(self.attachment_combo.currentData())
        if image is None or image.isNull():
            self.attachment_preview.setPixmap(QPixmap())
            self.attachment_preview.setText("附件生成失败；请查看下方 OpenGL 错误")
            return
        pixmap = QPixmap.fromImage(image).scaled(
            self.attachment_preview.size(), Qt.KeepAspectRatio,
            Qt.SmoothTransformation)
        self.attachment_preview.setText(""); self.attachment_preview.setPixmap(pixmap)

    def _reset(self):
        defaults = Pipeline3DConfig(source_mode=self.config.source_mode,
                                    extrusion_depth=self.config.extrusion_depth)
        self.config = defaults; self.viewport.set_config(defaults); self.refresh()

    def _controls_changed(self):
        if self._updating: return
        try:
            new_config = self.config.changed(
                source_mode=self.source_combo.currentData(),
                extrusion_depth=self.depth_spin.value(),
                view_mode=self.mode_combo.currentData(),
                depth_test=self.depth_check.isChecked(),
                cull_back_faces=self.cull_check.isChecked(),
                fov=self.fov_spin.value(), near=self.near_spin.value(),
                far=max(self.far_spin.value(), self.near_spin.value() + 0.1),
                rotation_x=self.rx_spin.value(), rotation_y=self.ry_spin.value(),
                rotation_z=self.rz_spin.value(), trace_vertex=self.vertex_spin.value(),
                light_x=self.light_x_spin.value(), light_y=self.light_y_spin.value(),
                light_z=self.light_z_spin.value(), ambient=self.ambient_spin.value(),
                diffuse=self.diffuse_spin.value(), specular=self.specular_spin.value(),
                shininess=self.shininess_spin.value(), shadows=self.shadow_check.isChecked(),
                shadow_resolution=self.shadow_resolution_combo.currentData(),
                shadow_bias=self.bias_spin.value(), pcf_radius=self.pcf_combo.currentData(),
                render_path=self.render_path_combo.currentData(),
                light_count=self.light_count_combo.currentData())
        except ValueError as error:
            self.source_warning = str(error); self.refresh(); return
        mesh_changed = (new_config.source_mode != self.config.source_mode or
                        new_config.extrusion_depth != self.config.extrusion_depth)
        self.config = new_config; self.viewport.set_config(new_config)
        self._mark_software_stale()
        if mesh_changed: self._rebuild_mesh()
        self.refresh()

    def _document_changed(self, *args):
        if self.config.source_mode == "selection": self._rebuild_mesh()

    def _rebuild_mesh(self):
        self._mark_software_stale()
        self.source_shape_id = ""
        if self.config.source_mode == "selection":
            source = selected_mesh_source(self.canvas)
            if source.valid:
                mesh = extrude_mesh(source.contour, source.triangles,
                                    self.config.extrusion_depth)
                self.source_shape_id = source.shape_id; self.source_warning = mesh.error
            else:
                mesh = cube_mesh(); self.source_warning = source.warning + "；已回退立方体"
        else:
            mesh = cube_mesh(); self.source_warning = ""
        self.viewport.set_mesh(mesh)
        self.vertex_spin.setMaximum(max(0, mesh.vertex_count - 1))
        self.refresh()

    def refresh(self):
        if not hasattr(self, "state_label"): return
        self._updating = True
        controls = (self.source_combo, self.depth_spin, self.mode_combo,
                    self.depth_check, self.cull_check, self.fov_spin,
                    self.near_spin, self.far_spin, self.rx_spin,
                    self.ry_spin, self.rz_spin, self.vertex_spin,
                    self.light_x_spin, self.light_y_spin, self.light_z_spin,
                    self.ambient_spin, self.diffuse_spin, self.specular_spin,
                    self.shininess_spin, self.shadow_check,
                    self.shadow_resolution_combo, self.bias_spin, self.pcf_combo,
                    self.render_path_combo, self.light_count_combo)
        for control in controls: control.blockSignals(True)
        self.source_combo.setCurrentIndex(self.source_combo.findData(self.config.source_mode))
        self.depth_spin.setValue(self.config.extrusion_depth)
        self.mode_combo.setCurrentIndex(self.mode_combo.findData(self.config.view_mode))
        self.depth_check.setChecked(self.config.depth_test); self.cull_check.setChecked(self.config.cull_back_faces)
        self.fov_spin.setValue(self.config.fov); self.near_spin.setValue(self.config.near)
        self.far_spin.setValue(self.config.far); self.rx_spin.setValue(self.config.rotation_x)
        self.ry_spin.setValue(self.config.rotation_y); self.rz_spin.setValue(self.config.rotation_z)
        self.vertex_spin.setValue(min(self.config.trace_vertex, self.vertex_spin.maximum()))
        self.light_x_spin.setValue(self.config.light_x)
        self.light_y_spin.setValue(self.config.light_y)
        self.light_z_spin.setValue(self.config.light_z)
        self.ambient_spin.setValue(self.config.ambient)
        self.diffuse_spin.setValue(self.config.diffuse)
        self.specular_spin.setValue(self.config.specular)
        self.shininess_spin.setValue(self.config.shininess)
        self.shadow_check.setChecked(self.config.shadows)
        self.shadow_resolution_combo.setCurrentIndex(
            self.shadow_resolution_combo.findData(self.config.shadow_resolution))
        self.bias_spin.setValue(self.config.shadow_bias)
        self.pcf_combo.setCurrentIndex(self.pcf_combo.findData(self.config.pcf_radius))
        self.render_path_combo.setCurrentIndex(
            self.render_path_combo.findData(self.config.render_path))
        self.light_count_combo.setCurrentIndex(
            self.light_count_combo.findData(self.config.light_count))
        for control in controls: control.blockSignals(False)
        self._updating = False
        mesh = self.viewport.mesh; state = self.viewport.runtime_state()
        if self.config.render_path == "forward":
            self.path_note.setText(
                "Forward：几何与光照在同一 fragment pass；无 G-buffer 读写，"
                f"但每个可见 fragment 计算 {self.config.light_count} 个光源。")
        else:
            self.path_note.setText(
                "Deferred：Geometry MRT 写 position/normal/albedo，再由全屏 pass "
                f"计算 {self.config.light_count} 个光源；本窗口估算每帧 G-buffer "
                f"读写 {state['deferred_frame_bytes'] / 1048576:.2f} MiB。")
        if mesh.vertices:
            index = min(self.config.trace_vertex, len(mesh.vertices) - 1)
            trace = trace_pipeline_vertex(mesh.vertices[index], self.config,
                                          max(1, self.viewport.width()),
                                          max(1, self.viewport.height()))
            rows = [(name, trace[name]) for name in
                    ("object", "world", "view", "clip", "ndc", "screen")]
            self.trace_table.setRowCount(len(rows) + 1)
            for row, (name, values) in enumerate(rows):
                self.trace_table.setItem(row, 0, QTableWidgetItem(name))
                self.trace_table.setItem(row, 1, QTableWidgetItem(
                    "(" + ", ".join(f"{value:.3f}" for value in values) + ")"))
            self.trace_table.setItem(len(rows), 0, QTableWidgetItem("clip test"))
            self.trace_table.setItem(len(rows), 1, QTableWidgetItem(
                "inside" if trace["inside_clip"] else "outside"))
        warning = f"\n提示：{self.source_warning}" if self.source_warning else ""
        error = f"\n错误：{state['error']}" if state["error"] else ""
        self.state_label.setText(
            f"Mesh backend: {mesh.backend} · source {self.source_shape_id or 'cube'}\n"
            f"Vertices {state['vertices']} · Triangles {state['triangles']} · "
            f"VBO {state['vbo_bytes']} bytes · Upload {state['upload_count']}\n"
            f"OpenGL {state['context_version']} · Draw calls {state['draw_calls']} · "
            f"CPU submit {state['draw_ms']:.3f} ms\n"
            f"Blinn-Phong A/D/S {self.config.ambient:.2f}/{self.config.diffuse:.2f}/"
            f"{self.config.specular:.2f} · shininess {self.config.shininess:.0f}\n"
            f"Shadow {self.config.shadow_resolution}² · bias {self.config.shadow_bias:.4f} · "
            f"PCF {(self.config.pcf_radius * 2 + 1)}² · approx "
            f"{state['shadow_bytes'] / 1048576:.2f} MiB · passes {state['shadow_passes']}\n"
            f"Path {self.config.render_path.title()} · lights {self.config.light_count} · "
            f"G-buffer {state['gbuffer_size'][0]}×{state['gbuffer_size'][1]} · "
            f"approx {state['gbuffer_bytes'] / 1048576:.2f} MiB\n"
            f"G-buffer passes {state['gbuffer_passes']} · lighting passes "
            f"{state['lighting_passes']} · manual attachments "
            f"{state['attachment_passes']}{warning}{error}")
