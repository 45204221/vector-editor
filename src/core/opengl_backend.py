"""Experimental OpenGL renderer consuming the stable GPU buffer frame."""

import ctypes
import os
import struct
import time
from collections import deque

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (QColor, QFont, QOpenGLBuffer, QOpenGLContext,
                         QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat,
                         QOpenGLShader, QOpenGLShaderProgram, QOpenGLTexture,
                         QOpenGLVersionProfile, QOpenGLVertexArrayObject, QPen, QTransform,
                         QVector2D, QVector3D, QVector4D)

from .gpu_buffers import (GpuBufferBuilder, GpuCommandKind, GpuTextCommand, GpuTopology,
                          GpuUploadKind, VERTEX_STRIDE_BYTES, plan_gpu_upload)
from .gpu_arena import GpuArena
from .rendering import CommandQPainterBackend, _draw_engine_debug, _draw_grid
from .raster_experiments import RasterExperimentConfig
from .offscreen_experiments import (PickComparison, decode_pick_id,
                                    encode_pick_id, estimated_target_bytes,
                                    offscreen_dimensions, validate_attachment_view,
                                    validate_picking_mode, validate_postprocess)
from .instancing_experiment import (ATLAS_SIZE, InstancingConfig,
                                    build_instance_data, build_sprite_atlas)
from .glyph_atlas import (ATLAS_SIZE as GLYPH_ATLAS_SIZE, GpuTextConfig,
                          TEXT_VERTEX_STRIDE, build_text_frame)
from .lighting_gpu import (LIGHT_VERTEX_STRIDE, build_multi_light_fan,
                           device_light_parameters, estimated_lighting_bytes)


GL_BLEND = 0x0BE2
GL_FLOAT = 0x1406
GL_TRIANGLES = 0x0004
GL_TRIANGLE_FAN = 0x0006
GL_MULTISAMPLE = 0x809D
GL_SRC_ALPHA = 0x0302
GL_ONE_MINUS_SRC_ALPHA = 0x0303
GL_ONE = 1
GL_ZERO = 0
GL_DST_COLOR = 0x0306
GL_SCISSOR_TEST = 0x0C11
GL_STENCIL_TEST = 0x0B90
GL_STENCIL_BUFFER_BIT = 0x00000400
GL_COLOR_BUFFER_BIT = 0x00004000
GL_RGBA = 0x1908
GL_RGBA8 = 0x8058
GL_UNSIGNED_BYTE = 0x1401
GL_TEXTURE0 = 0x84C0
GL_TEXTURE_2D = 0x0DE1
GL_EQUAL = 0x0202
GL_KEEP = 0x1E00
GL_TIME_ELAPSED = 0x88BF
GL_QUERY_RESULT = 0x8866
GL_QUERY_RESULT_AVAILABLE = 0x8867

VERTEX_SHADER = """
attribute vec2 a_position;
attribute vec4 a_color;
uniform vec4 u_transform;
uniform vec2 u_translate;
uniform vec2 u_viewport;
varying vec4 v_color;
varying vec2 v_screen_uv;
void main() {
    vec2 device = vec2(
        u_transform.x * a_position.x + u_transform.z * a_position.y + u_translate.x,
        u_transform.y * a_position.x + u_transform.w * a_position.y + u_translate.y
    );
    vec2 clip = vec2(device.x * 2.0 / u_viewport.x - 1.0,
                     1.0 - device.y * 2.0 / u_viewport.y);
    gl_Position = vec4(clip, 0.0, 1.0);
    v_color = a_color;
    v_screen_uv = device / u_viewport;
}
"""

FRAGMENT_SHADER = """
#ifdef GL_ES
precision mediump float;
#endif
varying vec4 v_color;
varying vec2 v_screen_uv;
uniform int u_shader_mode;
uniform float u_time;
uniform int u_pick_mode;
uniform vec4 u_pick_color;
void main() {
    if (u_pick_mode == 1) {
        if (v_color.a <= 0.001) discard;
        gl_FragColor = u_pick_color;
        return;
    }
    vec4 color = v_color;
    if (u_shader_mode == 1) {
        vec3 cool = vec3(0.25, 0.68, 1.0);
        vec3 warm = vec3(1.0, 0.30, 0.52);
        vec3 tint = mix(cool, warm, clamp(v_screen_uv.y, 0.0, 1.0));
        color.rgb = mix(color.rgb, tint, 0.55);
    } else if (u_shader_mode == 2) {
        float pulse = 0.62 + 0.38 * sin(u_time * 2.5 + v_screen_uv.x * 6.2831853);
        color.rgb *= pulse;
    } else if (u_shader_mode == 3) {
        color = vec4(vec3(v_color.a), 1.0);
    }
    gl_FragColor = color;
}
"""

POST_VERTEX_SHADER = """
attribute vec2 a_position;
attribute vec2 a_uv;
varying vec2 v_uv;
void main() {
    gl_Position = vec4(a_position, 0.0, 1.0);
    v_uv = a_uv;
}
"""

POST_FRAGMENT_SHADER = """
#ifdef GL_ES
precision mediump float;
#endif
uniform sampler2D u_texture;
uniform int u_effect;
uniform vec2 u_texel_size;
varying vec2 v_uv;

float luminance(vec3 color) {
    return dot(color, vec3(0.2126, 0.7152, 0.0722));
}

void main() {
    vec4 source = texture2D(u_texture, v_uv);
    if (u_effect == 1) {
        float value = luminance(source.rgb);
        gl_FragColor = vec4(vec3(value), source.a);
    } else if (u_effect == 2) {
        gl_FragColor = vec4(vec3(1.0) - source.rgb, source.a);
    } else if (u_effect == 3) {
        float left = luminance(texture2D(u_texture, v_uv - vec2(u_texel_size.x, 0.0)).rgb);
        float right = luminance(texture2D(u_texture, v_uv + vec2(u_texel_size.x, 0.0)).rgb);
        float down = luminance(texture2D(u_texture, v_uv - vec2(0.0, u_texel_size.y)).rgb);
        float up = luminance(texture2D(u_texture, v_uv + vec2(0.0, u_texel_size.y)).rgb);
        float edge = clamp(length(vec2(right - left, up - down)) * 2.5, 0.0, 1.0);
        gl_FragColor = vec4(vec3(edge), 1.0);
    } else {
        gl_FragColor = source;
    }
}
"""

LIGHT_MASK_VERTEX_SHADER = """
attribute vec2 a_position;
uniform vec4 u_transform;
uniform vec2 u_translate;
uniform vec2 u_viewport;
void main() {
    vec2 device = vec2(
        u_transform.x * a_position.x + u_transform.z * a_position.y + u_translate.x,
        u_transform.y * a_position.x + u_transform.w * a_position.y + u_translate.y
    );
    gl_Position = vec4(device.x * 2.0 / u_viewport.x - 1.0,
                       1.0 - device.y * 2.0 / u_viewport.y, 0.0, 1.0);
}
"""

LIGHT_MASK_FRAGMENT_SHADER = """
#ifdef GL_ES
precision mediump float;
#endif
void main() { gl_FragColor = vec4(1.0); }
"""

LIGHT_FRAGMENT_SHADER = """
#ifdef GL_ES
precision mediump float;
#endif
uniform sampler2D u_texture;
uniform int u_stage;
uniform vec2 u_light_device;
uniform float u_radius_device;
uniform float u_intensity;
uniform float u_ambient;
uniform vec3 u_light_color;
uniform vec2 u_viewport;
varying vec2 v_uv;
void main() {
    vec4 source = texture2D(u_texture, v_uv);
    if (u_stage == 1) {
        gl_FragColor = source;
        return;
    }
    float distance_to_light = distance(v_uv * u_viewport, u_light_device);
    float attenuation = 1.0 - smoothstep(0.0, max(1.0, u_radius_device),
                                         distance_to_light);
    float visible_light = source.r * attenuation * u_intensity;
    vec3 light = clamp(vec3(u_ambient) + u_light_color * visible_light,
                       vec3(0.0), vec3(1.0));
    gl_FragColor = vec4(light, 1.0);
}
"""

SPRITE_VERTEX_SHADER = """
attribute vec2 a_corner;
attribute vec2 a_uv;
attribute vec2 i_base;
attribute vec2 i_velocity;
attribute float i_size;
attribute float i_rotation;
attribute vec4 i_color;
attribute vec4 i_uv_rect;
uniform vec4 u_transform;
uniform vec2 u_translate;
uniform vec2 u_viewport;
uniform vec2 u_canvas_size;
uniform float u_time;
uniform int u_animate;
varying vec2 v_uv;
varying vec4 v_color;
void main() {
    vec2 motion = i_base + (u_animate == 1 ? i_velocity * u_time : vec2(0.0));
    vec2 center = mod(mod(motion, u_canvas_size) + u_canvas_size, u_canvas_size);
    float angle = i_rotation + (u_animate == 1 ? u_time * 0.35 : 0.0);
    float c = cos(angle);
    float s = sin(angle);
    vec2 local = vec2(c * a_corner.x - s * a_corner.y,
                      s * a_corner.x + c * a_corner.y) * i_size;
    vec2 scene = center + local;
    vec2 device = vec2(
        u_transform.x * scene.x + u_transform.z * scene.y + u_translate.x,
        u_transform.y * scene.x + u_transform.w * scene.y + u_translate.y
    );
    vec2 clip = vec2(device.x * 2.0 / u_viewport.x - 1.0,
                     1.0 - device.y * 2.0 / u_viewport.y);
    gl_Position = vec4(clip, 0.0, 1.0);
    v_uv = mix(i_uv_rect.xy, i_uv_rect.zw, a_uv);
    v_color = i_color;
}
"""

TEXT_VERTEX_SHADER = """
attribute vec2 a_position;
attribute vec2 a_uv;
attribute vec4 a_color;
uniform vec4 u_transform;
uniform vec2 u_translate;
uniform vec2 u_viewport;
varying vec2 v_uv;
varying vec4 v_color;
void main() {
    vec2 device = vec2(
        u_transform.x * a_position.x + u_transform.z * a_position.y + u_translate.x,
        u_transform.y * a_position.x + u_transform.w * a_position.y + u_translate.y
    );
    gl_Position = vec4(device.x * 2.0 / u_viewport.x - 1.0,
                       1.0 - device.y * 2.0 / u_viewport.y, 0.0, 1.0);
    v_uv = a_uv;
    v_color = a_color;
}
"""

TEXT_FRAGMENT_SHADER = """
#ifdef GL_ES
precision mediump float;
#endif
uniform sampler2D u_glyph_atlas;
varying vec2 v_uv;
varying vec4 v_color;
void main() {
    float coverage = texture2D(u_glyph_atlas, v_uv).a;
    if (coverage <= 0.01) discard;
    gl_FragColor = vec4(v_color.rgb, v_color.a * coverage);
}
"""

SPRITE_FRAGMENT_SHADER = """
#ifdef GL_ES
precision mediump float;
#endif
uniform sampler2D u_atlas;
varying vec2 v_uv;
varying vec4 v_color;
void main() {
    vec4 texel = texture2D(u_atlas, v_uv);
    vec4 result = texel * v_color;
    if (result.a <= 0.01) discard;
    gl_FragColor = result;
}
"""


class _NativeOpenGLFunctions:
    """Minimal Qt-resolved GL table for PyQt builds without versionFunctions wrappers."""

    def __init__(self, context):
        factory = ctypes.WINFUNCTYPE if os.name == "nt" else ctypes.CFUNCTYPE
        self.glEnable = self._resolve(context, factory, "glEnable", None, ctypes.c_uint)
        self.glDisable = self._resolve(context, factory, "glDisable", None, ctypes.c_uint)
        self.glBlendFunc = self._resolve(context, factory, "glBlendFunc", None,
                                        ctypes.c_uint, ctypes.c_uint)
        self.glScissor = self._resolve(context, factory, "glScissor", None,
                                      ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int)
        self.glClearStencil = self._resolve(context, factory, "glClearStencil", None,
                                           ctypes.c_int)
        self.glClear = self._resolve(context, factory, "glClear", None, ctypes.c_uint)
        self.glClearColor = self._resolve(context, factory, "glClearColor", None,
                                         ctypes.c_float, ctypes.c_float,
                                         ctypes.c_float, ctypes.c_float)
        self.glViewport = self._resolve(context, factory, "glViewport", None,
                                       ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int)
        self.glReadPixels = self._resolve(context, factory, "glReadPixels", None,
                                         ctypes.c_int, ctypes.c_int,
                                         ctypes.c_int, ctypes.c_int,
                                         ctypes.c_uint, ctypes.c_uint,
                                         ctypes.c_void_p)
        self.glActiveTexture = self._resolve(context, factory, "glActiveTexture", None,
                                            ctypes.c_uint)
        self.glBindTexture = self._resolve(context, factory, "glBindTexture", None,
                                          ctypes.c_uint, ctypes.c_uint)
        self.glVertexAttribDivisor = self._resolve(
            context, factory, "glVertexAttribDivisor", None,
            ctypes.c_uint, ctypes.c_uint)
        self.glDrawArraysInstanced = self._resolve(
            context, factory, "glDrawArraysInstanced", None,
            ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_int)
        self.glStencilMask = self._resolve(context, factory, "glStencilMask", None,
                                          ctypes.c_uint)
        self.glStencilFunc = self._resolve(context, factory, "glStencilFunc", None,
                                          ctypes.c_uint, ctypes.c_int, ctypes.c_uint)
        self.glStencilOp = self._resolve(context, factory, "glStencilOp", None,
                                        ctypes.c_uint, ctypes.c_uint, ctypes.c_uint)
        self.glDrawArrays = self._resolve(context, factory, "glDrawArrays", None,
                                         ctypes.c_uint, ctypes.c_int, ctypes.c_int)

    @staticmethod
    def _resolve(context, factory, name, result_type, *argument_types):
        address = context.getProcAddress(name.encode("ascii"))
        pointer = int(address) if address is not None else 0
        if not pointer:
            raise RuntimeError(f"OpenGL function is unavailable: {name}")
        return factory(result_type, *argument_types)(pointer)

    def initializeOpenGLFunctions(self):
        return True


class _GpuTimerQueryPool:
    """Non-blocking GL_TIME_ELAPSED ring; busy queries are skipped, never waited on."""

    def __init__(self, context, size=4):
        factory = ctypes.WINFUNCTYPE if os.name == "nt" else ctypes.CFUNCTYPE
        resolve = _NativeOpenGLFunctions._resolve
        self.glGenQueries = resolve(context, factory, "glGenQueries", None,
                                    ctypes.c_int, ctypes.POINTER(ctypes.c_uint))
        self.glDeleteQueries = resolve(context, factory, "glDeleteQueries", None,
                                       ctypes.c_int, ctypes.POINTER(ctypes.c_uint))
        self.glBeginQuery = resolve(context, factory, "glBeginQuery", None,
                                   ctypes.c_uint, ctypes.c_uint)
        self.glEndQuery = resolve(context, factory, "glEndQuery", None, ctypes.c_uint)
        self.glGetQueryObjectiv = resolve(
            context, factory, "glGetQueryObjectiv", None,
            ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_int))
        self.glGetQueryObjectui64v = resolve(
            context, factory, "glGetQueryObjectui64v", None,
            ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_uint64))
        query_ids = (ctypes.c_uint * max(2, int(size)))()
        self.glGenQueries(len(query_ids), query_ids)
        self._all_ids = tuple(int(query_id) for query_id in query_ids)
        if not all(self._all_ids):
            raise RuntimeError("OpenGL timer query allocation failed")
        self._free = deque(self._all_ids)
        self._pending = deque()
        self._active = None

    def poll(self, profiler):
        while self._pending:
            query_id = self._pending[0]
            available = ctypes.c_int()
            self.glGetQueryObjectiv(
                query_id, GL_QUERY_RESULT_AVAILABLE, ctypes.byref(available))
            if not available.value:
                break
            elapsed_ns = ctypes.c_uint64()
            self.glGetQueryObjectui64v(
                query_id, GL_QUERY_RESULT, ctypes.byref(elapsed_ns))
            self._pending.popleft()
            self._free.append(query_id)
            profiler.record_ms("gpu_draw", elapsed_ns.value / 1_000_000.0)

    def begin(self, profiler):
        self.poll(profiler)
        if self._active is not None or not self._free:
            return False
        self._active = self._free.popleft()
        self.glBeginQuery(GL_TIME_ELAPSED, self._active)
        return True

    def end(self):
        if self._active is None:
            return
        self.glEndQuery(GL_TIME_ELAPSED)
        self._pending.append(self._active)
        self._active = None

    def release(self):
        if not self._all_ids:
            return
        query_ids = (ctypes.c_uint * len(self._all_ids))(*self._all_ids)
        self.glDeleteQueries(len(query_ids), query_ids)
        self._all_ids = ()
        self._free.clear()
        self._pending.clear()
        self._active = None


class OpenGLBackend(CommandQPainterBackend):
    """Draw vectors with OpenGL and retain QPainter for text/editor overlays."""

    def __init__(self, canvas, experiment=None):
        super().__init__(canvas)
        self.experiment = experiment or RasterExperimentConfig()
        self._experiment_started = time.perf_counter()
        self.last_effective_clip_mode = "none"
        self.last_time_uniform = 0.0
        self.last_experiment_warning = ""
        self.stencil_bits = 0
        self.picking_mode = "cpu"
        self.id_target = None
        self.id_target_size = (0, 0)
        self.pick_id_to_shape = {}
        self.last_pick = PickComparison()
        self.last_id_target_error = ""
        self.last_id_target_revision = -1
        self.color_target = None
        self.post_target = None
        self.offscreen_target_size = (0, 0)
        self.post_program = None
        self.post_buffer = None
        self.post_vertex_array = None
        self.last_offscreen_effect = "none"
        self.last_offscreen_ms = 0.0
        self.last_offscreen_bytes = 0
        self.last_offscreen_error = ""
        self._last_frame = None
        self._last_transform = None
        self._last_device_size = (0, 0)
        self.instancing_config = InstancingConfig()
        self.sprite_program = None
        self.sprite_quad_buffer = None
        self.sprite_instance_buffer = None
        self.sprite_vertex_array = None
        self.sprite_texture = None
        self.instancing_dirty = True
        self.instancing_upload_count = 0
        self.last_instancing_error = ""
        self.last_instancing_draw_calls = 0
        self.last_instancing_bytes = 0
        self.last_instancing_time = 0.0
        self._instancing_started = time.perf_counter()
        self.gpu_text_config = GpuTextConfig()
        self.text_program = None
        self.text_buffer = None
        self.text_vertex_array = None
        self.text_texture = None
        self.text_frame = None
        self.text_upload_count = 0
        self.text_atlas_rebuild_count = 0
        self.last_text_draw_calls = 0
        self.last_text_fallback_commands = 0
        self.last_text_error = ""
        self.lighting_snapshot = None
        self.light_mask_target = None
        self.light_target = None
        self.lighting_target_size = (0, 0)
        self.light_mask_program = None
        self.light_program = None
        self.light_fan_buffer = None
        self.light_fan_vertex_array = None
        self.light_quad_buffer = None
        self.light_quad_vertex_array = None
        self.light_fan_frame = None
        self.lighting_upload_count = 0
        self.last_lighting_draw_calls = 0
        self.last_lighting_ms = 0.0
        self.last_lighting_bytes = 0
        self.last_lighting_error = ""
        self.lighting_active = False
        self.buffer_builder = GpuBufferBuilder()
        self.arena = GpuArena()
        self.program = None
        self.vertex_buffer = None
        self.vertex_array = None
        self.context = None
        self.functions = None
        self.last_error = ""
        self.last_gpu_vertices = 0
        self.last_gpu_batches = 0
        self.last_upload_kind = GpuUploadKind.NONE
        self.last_upload_bytes = 0
        self.last_upload_ranges = 0
        self.full_upload_count = 0
        self.partial_upload_count = 0
        self.fallback_active = False
        self._uploaded_frame = None
        self._frame_cache_key = None
        self._frame_cache = None
        self._gpu_layout_generation = -1
        self.gpu_timer_queries = None

    def set_picking_mode(self, mode):
        self.picking_mode = validate_picking_mode(mode)
        if mode == "cpu":
            self.last_pick = PickComparison()

    def set_instancing_config(self, config):
        if not isinstance(config, InstancingConfig):
            raise TypeError("config must be InstancingConfig")
        data_changed = (config.count != self.instancing_config.count
                        or config.sprite_mode != self.instancing_config.sprite_mode
                        or config.seed != self.instancing_config.seed)
        if data_changed:
            self.instancing_dirty = True
        if config.enabled != self.instancing_config.enabled:
            self._instancing_started = time.perf_counter()
        self.instancing_config = config

    def instancing_state(self):
        return {
            "enabled": self.instancing_config.enabled,
            "count": self.instancing_config.count,
            "sprite_mode": self.instancing_config.sprite_mode,
            "animate": self.instancing_config.animate,
            "seed": self.instancing_config.seed,
            "resources_valid": bool(self.sprite_program and self.sprite_texture
                                    and self.sprite_texture.isCreated()),
            "atlas_size": ATLAS_SIZE,
            "instance_bytes": self.last_instancing_bytes,
            "upload_count": self.instancing_upload_count,
            "draw_calls": self.last_instancing_draw_calls,
            "time_uniform": self.last_instancing_time,
            "error": self.last_instancing_error,
        }

    def set_gpu_text_config(self, config):
        if not isinstance(config, GpuTextConfig):
            raise TypeError("config must be GpuTextConfig")
        self.gpu_text_config = config

    def gpu_text_state(self):
        frame = self.text_frame
        return {
            "enabled": self.gpu_text_config.enabled,
            "show_demo": self.gpu_text_config.show_demo,
            "resources_valid": bool(self.text_program and self.text_texture
                                    and self.text_texture.isCreated()),
            "atlas_size": GLYPH_ATLAS_SIZE,
            "atlas_bytes": GLYPH_ATLAS_SIZE[0] * GLYPH_ATLAS_SIZE[1] * 4,
            "unique_glyphs": len(frame.cells) if frame else 0,
            "rendered_glyphs": frame.glyph_count if frame else 0,
            "vertices": frame.vertex_count if frame else 0,
            "vbo_bytes": len(frame.payload) if frame else 0,
            "draw_calls": self.last_text_draw_calls,
            "upload_count": self.text_upload_count,
            "atlas_rebuild_count": self.text_atlas_rebuild_count,
            "fallback_commands": self.last_text_fallback_commands,
            "error": self.last_text_error,
        }

    def set_lighting_snapshot(self, snapshot):
        self.lighting_snapshot = snapshot

    def lighting_state(self):
        frame = self.light_fan_frame
        return {
            "gpu_supported": True,
            "gpu_requested": bool(self.lighting_snapshot and
                                  self.lighting_snapshot.config.gpu_lighting),
            "gpu_active": self.lighting_active,
            "light_count": len(self.lighting_snapshot.light_visibilities)
                           if self.lighting_snapshot else 0,
            "target_size": self.lighting_target_size,
            "mask_valid": bool(self.light_mask_target and
                               self.light_mask_target.isValid()),
            "light_valid": bool(self.light_target and self.light_target.isValid()),
            "fbo_bytes": self.last_lighting_bytes,
            "fan_vertices": frame.vertex_count if frame else 0,
            "fan_vbo_bytes": len(frame.payload) if frame else 0,
            "upload_count": self.lighting_upload_count,
            "draw_calls": self.last_lighting_draw_calls,
            "pass_ms": self.last_lighting_ms,
            "error": self.last_lighting_error,
        }

    def lighting_attachment_image(self, attachment):
        target = self.light_mask_target if attachment == "mask" else self.light_target
        if attachment not in ("mask", "light"):
            raise ValueError("lighting attachment must be mask or light")
        if target is None or not target.isValid():
            self.last_lighting_error = "光照附件尚未生成"
            return None
        return target.toImage()

    def record_pick_comparison(self, comparison):
        if not isinstance(comparison, PickComparison):
            raise TypeError("comparison must be PickComparison")
        self.last_pick = comparison

    def offscreen_state(self):
        return {
            "picking_mode": self.picking_mode,
            "target_size": self.id_target_size,
            "target_valid": bool(self.id_target and self.id_target.isValid()),
            "target_revision": self.last_id_target_revision,
            "attachment": "RGBA8 object ID + CombinedDepthStencil",
            "mapped_shapes": len(self.pick_id_to_shape),
            "cpu_shape_id": self.last_pick.cpu_shape_id,
            "gpu_shape_id": self.last_pick.gpu_shape_id,
            "cpu_ms": self.last_pick.cpu_ms,
            "gpu_ms": self.last_pick.gpu_ms,
            "matched": self.last_pick.matched,
            "gpu_available": self.last_pick.gpu_available,
            "warning": self.last_pick.fallback_reason or self.last_id_target_error,
            "color_target_size": self.offscreen_target_size,
            "color_target_valid": bool(self.color_target and self.color_target.isValid()),
            "post_target_valid": bool(self.post_target and self.post_target.isValid()),
            "postprocess_effect": self.last_offscreen_effect,
            "offscreen_ms": self.last_offscreen_ms,
            "offscreen_bytes": self.last_offscreen_bytes,
            "offscreen_error": self.last_offscreen_error,
        }

    def set_experiment(self, experiment):
        if not isinstance(experiment, RasterExperimentConfig):
            raise TypeError("experiment must be RasterExperimentConfig")
        if experiment.shader_mode != self.experiment.shader_mode:
            self._experiment_started = time.perf_counter()
        self.experiment = experiment

    def experiment_state(self):
        state = self.experiment.as_dict()
        state.update({
            "effective_clip_mode": self.last_effective_clip_mode,
            "stencil_bits": self.stencil_bits,
            "time_uniform": self.last_time_uniform,
            "active": self.program is not None and not self.fallback_active,
            "warning": self.last_experiment_warning,
        })
        return state

    def sync_document(self, document, dirty_flags):
        with self.canvas.profiler.measure("geometry"):
            self.cache.apply_delta(document)
        with self.canvas.profiler.measure("arena_update"):
            self.arena.apply_delta(document, self.cache)

    def release(self):
        context = QOpenGLContext.currentContext()
        if context is self.context:
            if self.gpu_timer_queries:
                self.gpu_timer_queries.release()
            if self.vertex_array and self.vertex_array.isCreated():
                self.vertex_array.destroy()
            if self.vertex_buffer and self.vertex_buffer.isCreated():
                self.vertex_buffer.destroy()
            if self.program:
                self.program.removeAllShaders()
            if self.post_program:
                self.post_program.removeAllShaders()
            if self.post_vertex_array and self.post_vertex_array.isCreated():
                self.post_vertex_array.destroy()
            if self.post_buffer and self.post_buffer.isCreated():
                self.post_buffer.destroy()
            if self.sprite_vertex_array and self.sprite_vertex_array.isCreated():
                self.sprite_vertex_array.destroy()
            if self.sprite_quad_buffer and self.sprite_quad_buffer.isCreated():
                self.sprite_quad_buffer.destroy()
            if self.sprite_instance_buffer and self.sprite_instance_buffer.isCreated():
                self.sprite_instance_buffer.destroy()
            if self.sprite_program:
                self.sprite_program.removeAllShaders()
            if self.sprite_texture and self.sprite_texture.isCreated():
                self.sprite_texture.destroy()
            if self.text_vertex_array and self.text_vertex_array.isCreated():
                self.text_vertex_array.destroy()
            if self.text_buffer and self.text_buffer.isCreated():
                self.text_buffer.destroy()
            if self.text_program:
                self.text_program.removeAllShaders()
            if self.text_texture and self.text_texture.isCreated():
                self.text_texture.destroy()
            if self.light_mask_program:
                self.light_mask_program.removeAllShaders()
            if self.light_program:
                self.light_program.removeAllShaders()
            if self.light_fan_vertex_array and self.light_fan_vertex_array.isCreated():
                self.light_fan_vertex_array.destroy()
            if self.light_fan_buffer and self.light_fan_buffer.isCreated():
                self.light_fan_buffer.destroy()
            if self.light_quad_vertex_array and self.light_quad_vertex_array.isCreated():
                self.light_quad_vertex_array.destroy()
            if self.light_quad_buffer and self.light_quad_buffer.isCreated():
                self.light_quad_buffer.destroy()
            self.id_target = None
            self.color_target = None
            self.post_target = None
            self.light_mask_target = None
            self.light_target = None
        self.program = self.vertex_buffer = self.vertex_array = None
        self.context = self.functions = None
        self.gpu_timer_queries = None
        self._uploaded_frame = None
        self._gpu_layout_generation = -1
        self.id_target = None
        self.id_target_size = (0, 0)
        self.pick_id_to_shape.clear()
        self.last_id_target_revision = -1
        self.color_target = self.post_target = None
        self.offscreen_target_size = (0, 0)
        self.post_program = self.post_buffer = self.post_vertex_array = None
        self._last_frame = self._last_transform = None
        self.sprite_program = self.sprite_quad_buffer = None
        self.sprite_instance_buffer = self.sprite_vertex_array = None
        self.sprite_texture = None
        self.instancing_dirty = True
        self.text_program = self.text_buffer = self.text_vertex_array = None
        self.text_texture = None
        self.text_frame = None
        self.light_mask_target = self.light_target = None
        self.lighting_target_size = (0, 0)
        self.light_mask_program = self.light_program = None
        self.light_fan_buffer = self.light_fan_vertex_array = None
        self.light_quad_buffer = self.light_quad_vertex_array = None
        self.light_fan_frame = None
        self.lighting_active = False

    def render(self, painter, viewport=None):
        canvas = self.canvas
        viewport = (viewport or QRectF(0, 0, canvas.width, canvas.height)).intersected(
            QRectF(0, 0, canvas.width, canvas.height))
        viewport_bounds = (viewport.left(), viewport.top(), viewport.right(), viewport.bottom())
        with self.canvas.profiler.measure("arena_frame"):
            frame = self.arena.build_frame(self.cache, viewport_bounds)
        transform = painter.combinedTransform()
        device = painter.device()
        device_width = max(1.0, float(device.width()))
        device_height = max(1.0, float(device.height()))

        if self.arena.allocation_count and not self._upload_arena(painter):
            self.fallback_active = True
            super().render(painter, viewport)
            return
        if not self.arena.allocation_count:
            self.last_upload_kind = GpuUploadKind.NONE
            self.last_upload_bytes = self.last_upload_ranges = 0

        self.fallback_active = False
        self.last_primitive_count = frame.source_primitive_count
        self.last_gpu_vertices = frame.visible_vertex_count
        self.last_gpu_batches = len(frame.batches)
        self._last_frame = frame
        self._last_transform = transform
        self._last_device_size = (int(device_width), int(device_height))
        painter.save()
        painter.setRenderHint(painter.Antialiasing)
        painter.fillRect(QRectF(0, 0, canvas.width, canvas.height), QColor("white"))
        if canvas.show_grid:
            _draw_grid(painter, canvas, viewport)

        self.last_text_draw_calls = 0
        self.last_text_fallback_commands = 0
        text_commands = frame.text_commands
        demo_index = None
        if self.gpu_text_config.enabled and self.gpu_text_config.show_demo:
            demo_index = len(text_commands)
            text_commands = text_commands + (
                self._gpu_text_demo_command(device_width, device_height),)
        text_ready = False
        if self.gpu_text_config.enabled and text_commands:
            text_ready = self._prepare_gpu_text(painter, text_commands)

        index = 0
        while index < len(frame.command_stream):
            command = frame.command_stream[index]
            if command.kind == GpuCommandKind.TEXT:
                text_indexes = []
                while index < len(frame.command_stream):
                    command = frame.command_stream[index]
                    if command.kind != GpuCommandKind.TEXT:
                        break
                    text_indexes.append(command.index)
                    index += 1
                if not text_ready:
                    for text_index in text_indexes:
                        self._draw_text(painter, frame.text_commands[text_index])
                        if self.gpu_text_config.enabled:
                            self.last_text_fallback_commands += 1
                else:
                    self._draw_text_command_group(
                        painter, text_commands, text_indexes, transform,
                        device_width, device_height)
                continue
            batch_indexes = []
            while index < len(frame.command_stream):
                command = frame.command_stream[index]
                if command.kind != GpuCommandKind.BATCH:
                    break
                batch_indexes.append(command.index)
                index += 1
            if not self._draw_batches(painter, frame, batch_indexes, transform,
                                      device_width, device_height):
                painter.restore()
                self.fallback_active = True
                super().render(painter, viewport)
                return

        if demo_index is not None and text_ready:
            self._draw_text_command_group(
                painter, text_commands, [demo_index], QTransform(),
                device_width, device_height)

        self.last_instancing_draw_calls = 0
        if self.instancing_config.enabled:
            self._draw_instanced_sprites(
                painter, transform, device_width, device_height)
        self.last_lighting_draw_calls = 0
        self.lighting_active = False
        snapshot = self.lighting_snapshot
        if (snapshot is not None and snapshot.config.enabled
                and snapshot.config.gpu_lighting):
            self._draw_gpu_lighting(
                painter, snapshot, transform, int(device_width), int(device_height))
        self._draw_selection_overlay(painter)
        if canvas.show_engine_debug:
            visible = [shape for shape in canvas.sorted_shapes()
                       if shape.bounding_rect().intersects(viewport)]
            _draw_engine_debug(painter, canvas, visible)
        painter.restore()
        if self.picking_mode != "cpu":
            self._render_id_target(painter, frame, transform,
                                   int(device_width), int(device_height))

    def _upload_arena(self, painter):
        painter.beginNativePainting()
        try:
            if not self._ensure_resources():
                return False
            force_full = self._gpu_layout_generation != self.arena.layout_generation
            with self.canvas.profiler.measure("upload_plan"):
                upload_plan = self.arena.build_upload_plan(force_full=force_full)
            self.vertex_array.bind()
            self.vertex_buffer.bind()
            with self.canvas.profiler.measure("gpu_upload_cpu"):
                if upload_plan.kind == GpuUploadKind.FULL:
                    payload = upload_plan.ranges[0].payload
                    self.vertex_buffer.allocate(payload, len(payload))
                elif upload_plan.kind == GpuUploadKind.PARTIAL:
                    for update_range in upload_plan.ranges:
                        self.vertex_buffer.write(update_range.byte_offset, update_range.payload,
                                                 len(update_range.payload))
            self.program.bind()
            position = self.program.attributeLocation("a_position")
            color = self.program.attributeLocation("a_color")
            self.program.enableAttributeArray(position)
            self.program.setAttributeBuffer(position, GL_FLOAT, 0, 2, VERTEX_STRIDE_BYTES)
            self.program.enableAttributeArray(color)
            self.program.setAttributeBuffer(color, GL_FLOAT, 8, 4, VERTEX_STRIDE_BYTES)
            self.program.release()
            self.vertex_buffer.release()
            self.vertex_array.release()
            self.arena.mark_uploaded()
            self._gpu_layout_generation = self.arena.layout_generation
            if upload_plan.kind != GpuUploadKind.NONE:
                self.last_upload_kind = upload_plan.kind
                self.last_upload_bytes = upload_plan.byte_count
                self.last_upload_ranges = len(upload_plan.ranges)
                if upload_plan.kind == GpuUploadKind.FULL:
                    self.full_upload_count += 1
                else:
                    self.partial_upload_count += 1
            self.canvas.profiler.set_gauge("upload_bytes", upload_plan.byte_count)
            self.canvas.profiler.set_gauge("upload_ranges", len(upload_plan.ranges))
            return True
        except Exception as error:
            self.last_error = str(error)
            return False
        finally:
            painter.endNativePainting()

    def _upload_frame(self, painter, frame):
        painter.beginNativePainting()
        try:
            if not self._ensure_resources():
                return False
            upload_plan = plan_gpu_upload(self._uploaded_frame, frame)
            self.vertex_array.bind()
            self.vertex_buffer.bind()
            if upload_plan.kind == GpuUploadKind.FULL:
                payload = upload_plan.ranges[0].payload
                self.vertex_buffer.allocate(payload, len(payload))
            elif upload_plan.kind == GpuUploadKind.PARTIAL:
                for update_range in upload_plan.ranges:
                    self.vertex_buffer.write(update_range.byte_offset, update_range.payload,
                                             len(update_range.payload))
            self.program.bind()
            position = self.program.attributeLocation("a_position")
            color = self.program.attributeLocation("a_color")
            self.program.enableAttributeArray(position)
            self.program.setAttributeBuffer(position, GL_FLOAT, 0, 2, VERTEX_STRIDE_BYTES)
            self.program.enableAttributeArray(color)
            self.program.setAttributeBuffer(color, GL_FLOAT, 8, 4, VERTEX_STRIDE_BYTES)
            self.program.release()
            self.vertex_buffer.release()
            self.vertex_array.release()
            self._uploaded_frame = frame
            if upload_plan.kind != GpuUploadKind.NONE:
                self.last_upload_kind = upload_plan.kind
                self.last_upload_bytes = upload_plan.byte_count
                self.last_upload_ranges = len(upload_plan.ranges)
                if upload_plan.kind == GpuUploadKind.FULL:
                    self.full_upload_count += 1
                else:
                    self.partial_upload_count += 1
            return True
        except Exception as error:
            self.last_error = str(error)
            return False
        finally:
            painter.endNativePainting()

    def _ensure_resources(self):
        context = QOpenGLContext.currentContext()
        if context is None:
            self.last_error = "No current OpenGL context"
            return False
        if context is self.context and self.program is not None:
            return True
        self.release()
        self.context = context
        version_profile = QOpenGLVersionProfile(context.format())
        self.functions = context.versionFunctions(version_profile)
        if self.functions is None:
            try:
                self.functions = _NativeOpenGLFunctions(context)
            except Exception as error:
                self.last_error = str(error)
                return False
        self.functions.initializeOpenGLFunctions()
        context_format = context.format()
        self.canvas.profiler.set_metadata(
            "opengl_context_version",
            f"{context_format.majorVersion()}.{context_format.minorVersion()}")
        self.canvas.profiler.set_metadata("opengl_profile", int(context_format.profile()))
        self.canvas.profiler.set_metadata("opengl_msaa_samples", context_format.samples())
        self.canvas.profiler.set_gauge("opengl_msaa_samples", context_format.samples())
        self.stencil_bits = max(0, context_format.stencilBufferSize())
        self.canvas.profiler.set_metadata("opengl_stencil_bits", self.stencil_bits)
        self.canvas.profiler.set_gauge("opengl_stencil_bits", self.stencil_bits)
        try:
            self.gpu_timer_queries = _GpuTimerQueryPool(context)
            self.canvas.profiler.set_metadata(
                "gpu_timer_query", "available: asynchronous GL_TIME_ELAPSED blocks")
        except Exception as error:
            self.gpu_timer_queries = None
            self.canvas.profiler.set_metadata("gpu_timer_query", f"unavailable: {error}")
        program = QOpenGLShaderProgram()
        if not program.addShaderFromSourceCode(QOpenGLShader.Vertex, VERTEX_SHADER):
            self.last_error = program.log()
            return False
        if not program.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAGMENT_SHADER):
            self.last_error = program.log()
            return False
        if not program.link():
            self.last_error = program.log()
            return False
        vertex_buffer = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        vertex_array = QOpenGLVertexArrayObject()
        if not vertex_buffer.create() or not vertex_array.create():
            self.last_error = "Unable to create OpenGL buffer objects"
            return False
        self.program = program
        self.vertex_buffer = vertex_buffer
        self.vertex_array = vertex_array
        self.last_error = ""
        return True

    def _draw_batches(self, painter, frame, batch_indexes, transform, width, height):
        if not batch_indexes:
            return True
        painter.beginNativePainting()
        timer_started = False
        try:
            self.vertex_array.bind()
            self.vertex_buffer.bind()
            self.program.bind()
            self.program.setUniformValue("u_transform", QVector4D(
                transform.m11(), transform.m12(), transform.m21(), transform.m22()))
            self.program.setUniformValue("u_translate", QVector2D(transform.dx(), transform.dy()))
            self.program.setUniformValue("u_viewport", QVector2D(width, height))
            shader_index = {
                "vertex_color": 0, "screen_gradient": 1,
                "time_pulse": 2, "coverage": 3,
            }[self.experiment.shader_mode]
            self.last_time_uniform = max(0.0, time.perf_counter() - self._experiment_started)
            self.program.setUniformValue("u_shader_mode", shader_index)
            self.program.setUniformValue("u_time", self.last_time_uniform)
            self.program.setUniformValue("u_pick_mode", 0)
            self.program.setUniformValue("u_pick_color", QVector4D(0.0, 0.0, 0.0, 0.0))
            self.functions.glEnable(GL_MULTISAMPLE)
            if self.experiment.blend_mode == "opaque":
                self.functions.glDisable(GL_BLEND)
            else:
                self.functions.glEnable(GL_BLEND)
                destination = (GL_ONE if self.experiment.blend_mode == "additive"
                               else GL_ONE_MINUS_SRC_ALPHA)
                self.functions.glBlendFunc(GL_SRC_ALPHA, destination)
            self._configure_clip(width, height)
            if self.gpu_timer_queries and self.canvas.profiler.enabled:
                timer_started = self.gpu_timer_queries.begin(self.canvas.profiler)
            for batch_index in batch_indexes:
                batch = frame.batches[batch_index]
                if batch.topology != GpuTopology.TRIANGLES:
                    raise RuntimeError(f"Unsupported GPU topology: {batch.topology}")
                self.functions.glDrawArrays(
                    GL_TRIANGLES, batch.first_vertex, batch.vertex_count)
            if timer_started:
                self.gpu_timer_queries.end()
                timer_started = False
            self.program.release()
            self.vertex_buffer.release()
            self.vertex_array.release()
            return True
        except Exception as error:
            self.last_error = str(error)
            return False
        finally:
            if timer_started and self.gpu_timer_queries:
                try:
                    self.gpu_timer_queries.end()
                except Exception:
                    pass
            try:
                self.functions.glDisable(GL_SCISSOR_TEST)
                self.functions.glDisable(GL_STENCIL_TEST)
                self.functions.glStencilMask(0xFF)
                self.functions.glEnable(GL_BLEND)
                self.functions.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            except Exception:
                pass
            painter.endNativePainting()

    def _configure_clip(self, width, height):
        """Configure a centered device-space region for the vector pass."""
        requested = self.experiment.clip_mode
        self.last_experiment_warning = ""
        self.functions.glDisable(GL_SCISSOR_TEST)
        self.functions.glDisable(GL_STENCIL_TEST)
        self.functions.glStencilMask(0xFF)
        if requested == "none":
            self.last_effective_clip_mode = "none"
            return
        x = int(width * 0.20)
        y = int(height * 0.20)
        region_width = max(1, int(width * 0.60))
        region_height = max(1, int(height * 0.60))
        self.functions.glScissor(x, y, region_width, region_height)
        if requested == "scissor" or self.stencil_bits <= 0:
            self.functions.glEnable(GL_SCISSOR_TEST)
            self.last_effective_clip_mode = "scissor"
            if requested == "stencil":
                self.last_experiment_warning = (
                    "当前 OpenGL context 没有 stencil buffer，已回退到 Scissor。")
            return

        # Build a real stencil mask by clearing only the scissored center to 1.
        self.functions.glClearStencil(0)
        self.functions.glClear(GL_STENCIL_BUFFER_BIT)
        self.functions.glEnable(GL_SCISSOR_TEST)
        self.functions.glClearStencil(1)
        self.functions.glClear(GL_STENCIL_BUFFER_BIT)
        self.functions.glDisable(GL_SCISSOR_TEST)
        self.functions.glClearStencil(0)
        self.functions.glEnable(GL_STENCIL_TEST)
        self.functions.glStencilMask(0x00)
        self.functions.glStencilFunc(GL_EQUAL, 1, 0xFF)
        self.functions.glStencilOp(GL_KEEP, GL_KEEP, GL_KEEP)
        self.last_effective_clip_mode = "stencil"

    def _ensure_text_resources(self):
        if self.text_program is not None:
            return True
        program = QOpenGLShaderProgram()
        if not program.addShaderFromSourceCode(QOpenGLShader.Vertex, TEXT_VERTEX_SHADER):
            self.last_text_error = program.log()
            return False
        if not program.addShaderFromSourceCode(QOpenGLShader.Fragment, TEXT_FRAGMENT_SHADER):
            self.last_text_error = program.log()
            return False
        if not program.link():
            self.last_text_error = program.log()
            return False
        buffer = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        vertex_array = QOpenGLVertexArrayObject()
        if not buffer.create() or not vertex_array.create():
            self.last_text_error = "无法创建 glyph VAO/VBO"
            return False
        vertex_array.bind()
        buffer.bind()
        buffer.setUsagePattern(QOpenGLBuffer.DynamicDraw)
        program.bind()
        for name, offset, count in (("a_position", 0, 2), ("a_uv", 8, 2),
                                    ("a_color", 16, 4)):
            location = program.attributeLocation(name)
            program.enableAttributeArray(location)
            program.setAttributeBuffer(
                location, GL_FLOAT, offset, count, TEXT_VERTEX_STRIDE)
        program.release()
        buffer.release()
        vertex_array.release()
        self.text_program = program
        self.text_buffer = buffer
        self.text_vertex_array = vertex_array
        self.last_text_error = ""
        return True

    def _gpu_text_demo_command(self, device_width=900.0, device_height=600.0):
        # These coordinates are interpreted in device space when the runtime
        # overlay is submitted, so the explanation remains readable at any
        # editor zoom level.
        left, top = 24.0, 24.0
        right = max(left + 180.0, float(device_width) - 24.0)
        bottom = max(top + 70.0, min(float(device_height) - 16.0, 150.0))
        return GpuTextCommand(
            "__runtime_gpu_text_demo__", (left, top, right, bottom),
            ((left, top), (right, top), (right, bottom), (left, bottom)),
            (1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
            (0.04, 0.28, 0.48, 0.95),
            "GPU Glyph Atlas\n动态图集文字 / OpenGL",
            20.0,
        )

    def _prepare_gpu_text(self, painter, commands):
        key = tuple((command.shape_id, command.local_rect, command.transform,
                     command.color, command.text, command.font_size)
                    for command in commands)
        # GL resource loss is handled by release(), which clears text_frame.
        # isCreated() can fluctuate at Qt native-painting boundaries and must
        # not turn an unchanged pure-data key into a per-frame re-upload.
        if (self.text_frame is not None and self.text_frame.key == key
                and self.text_program is not None and self.text_texture is not None):
            return True
        painter.beginNativePainting()
        try:
            if not self._ensure_resources() or not self._ensure_text_resources():
                return False
            started = time.perf_counter()
            frame = build_text_frame(commands)
            if self.text_texture and self.text_texture.isCreated():
                self.text_texture.destroy()
            # QOpenGLTexture's QImage upload maps the image's top row to the
            # v=0 convention used by our atlas UVs. Mirroring here would move
            # the populated top atlas rows away from every recorded cell.
            texture = QOpenGLTexture(frame.image)
            if not texture.isCreated():
                self.last_text_error = "无法创建 glyph atlas texture"
                return False
            texture.generateMipMaps()
            texture.setMinificationFilter(QOpenGLTexture.LinearMipMapLinear)
            texture.setMagnificationFilter(QOpenGLTexture.Linear)
            texture.setWrapMode(QOpenGLTexture.ClampToEdge)
            self.text_vertex_array.bind()
            self.text_buffer.bind()
            self.text_buffer.allocate(frame.payload, len(frame.payload))
            self.text_buffer.release()
            self.text_vertex_array.release()
            self.text_texture = texture
            self.text_frame = frame
            self.text_upload_count += 1
            self.text_atlas_rebuild_count += 1
            self.last_text_error = ""
            self.canvas.profiler.record_ms(
                "glyph_atlas_rebuild", (time.perf_counter() - started) * 1000.0)
            return True
        except Exception as error:
            self.last_text_error = str(error)
            return False
        finally:
            painter.endNativePainting()

    def _draw_text_command_group(self, painter, commands, indexes,
                                 transform, width, height):
        supported = []

        def flush():
            if not supported:
                return
            if not self._draw_gpu_text_range(
                    painter, supported, transform, width, height):
                for item in supported:
                    self._draw_text(painter, commands[item])
                    self.last_text_fallback_commands += 1
            supported.clear()

        fallback_set = set(self.text_frame.fallback_indexes)
        for command_index in indexes:
            if command_index in fallback_set:
                flush()
                self._draw_text(painter, commands[command_index])
                self.last_text_fallback_commands += 1
            else:
                supported.append(command_index)
        flush()

    def _draw_gpu_text_range(self, painter, indexes, transform, width, height):
        non_empty = [self.text_frame.ranges[index] for index in indexes
                     if self.text_frame.ranges[index][1] > 0]
        if not non_empty:
            return True
        first_vertex = non_empty[0][0]
        last_first, last_count = non_empty[-1]
        vertex_count = last_first + last_count - first_vertex
        painter.beginNativePainting()
        try:
            started = time.perf_counter()
            self.text_vertex_array.bind()
            self.text_program.bind()
            self.text_texture.bind(0)
            self.text_program.setUniformValue("u_glyph_atlas", 0)
            self.text_program.setUniformValue("u_transform", QVector4D(
                transform.m11(), transform.m12(), transform.m21(), transform.m22()))
            self.text_program.setUniformValue(
                "u_translate", QVector2D(transform.dx(), transform.dy()))
            self.text_program.setUniformValue("u_viewport", QVector2D(width, height))
            self.functions.glDisable(GL_SCISSOR_TEST)
            self.functions.glDisable(GL_STENCIL_TEST)
            self.functions.glEnable(GL_BLEND)
            self.functions.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            self.functions.glDrawArrays(GL_TRIANGLES, first_vertex, vertex_count)
            self.text_texture.release()
            self.text_program.release()
            self.text_vertex_array.release()
            self.last_text_draw_calls += 1
            self.canvas.profiler.record_ms(
                "gpu_text_draw_cpu", (time.perf_counter() - started) * 1000.0)
            self.last_text_error = ""
            return True
        except Exception as error:
            self.last_text_error = str(error)
            return False
        finally:
            painter.endNativePainting()

    def _ensure_instancing_resources(self):
        if self.sprite_program is not None:
            return True
        program = QOpenGLShaderProgram()
        if not program.addShaderFromSourceCode(QOpenGLShader.Vertex, SPRITE_VERTEX_SHADER):
            self.last_instancing_error = program.log()
            return False
        if not program.addShaderFromSourceCode(QOpenGLShader.Fragment, SPRITE_FRAGMENT_SHADER):
            self.last_instancing_error = program.log()
            return False
        if not program.link():
            self.last_instancing_error = program.log()
            return False
        quad_values = (
            -0.5, -0.5, 0.0, 0.0,  0.5, -0.5, 1.0, 0.0,
             0.5,  0.5, 1.0, 1.0, -0.5, -0.5, 0.0, 0.0,
             0.5,  0.5, 1.0, 1.0, -0.5,  0.5, 0.0, 1.0,
        )
        quad_payload = struct.pack("<{}f".format(len(quad_values)), *quad_values)
        quad_buffer = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        instance_buffer = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        vertex_array = QOpenGLVertexArrayObject()
        if (not quad_buffer.create() or not instance_buffer.create()
                or not vertex_array.create()):
            self.last_instancing_error = "无法创建 sprite VAO/VBO"
            return False
        vertex_array.bind()
        quad_buffer.bind()
        quad_buffer.setUsagePattern(QOpenGLBuffer.StaticDraw)
        quad_buffer.allocate(quad_payload, len(quad_payload))
        program.bind()
        corner = program.attributeLocation("a_corner")
        uv = program.attributeLocation("a_uv")
        program.enableAttributeArray(corner)
        program.setAttributeBuffer(corner, GL_FLOAT, 0, 2, 16)
        program.enableAttributeArray(uv)
        program.setAttributeBuffer(uv, GL_FLOAT, 8, 2, 16)

        instance_buffer.bind()
        instance_buffer.setUsagePattern(QOpenGLBuffer.StaticDraw)
        attributes = (
            ("i_base", 0, 2), ("i_velocity", 8, 2),
            ("i_size", 16, 1), ("i_rotation", 20, 1),
            ("i_color", 24, 4), ("i_uv_rect", 40, 4),
        )
        for name, offset, count in attributes:
            location = program.attributeLocation(name)
            program.enableAttributeArray(location)
            program.setAttributeBuffer(location, GL_FLOAT, offset, count, 56)
            self.functions.glVertexAttribDivisor(location, 1)
        program.release()
        instance_buffer.release()
        quad_buffer.release()
        vertex_array.release()
        texture = QOpenGLTexture(build_sprite_atlas().mirrored())
        if not texture.isCreated():
            self.last_instancing_error = "无法创建 sprite atlas texture"
            return False
        texture.setMinificationFilter(QOpenGLTexture.Linear)
        texture.setMagnificationFilter(QOpenGLTexture.Linear)
        texture.setWrapMode(QOpenGLTexture.ClampToEdge)
        self.sprite_program = program
        self.sprite_quad_buffer = quad_buffer
        self.sprite_instance_buffer = instance_buffer
        self.sprite_vertex_array = vertex_array
        self.sprite_texture = texture
        self.instancing_dirty = True
        self.last_instancing_error = ""
        return True

    def _upload_instances(self):
        started = time.perf_counter()
        data = build_instance_data(
            self.instancing_config, self.canvas.width, self.canvas.height)
        self.sprite_instance_buffer.bind()
        self.sprite_instance_buffer.allocate(data.payload, len(data.payload))
        self.sprite_instance_buffer.release()
        self.last_instancing_bytes = len(data.payload)
        self.instancing_upload_count += 1
        self.instancing_dirty = False
        self.canvas.profiler.record_ms(
            "instance_upload", (time.perf_counter() - started) * 1000.0)

    def _draw_instanced_sprites(self, painter, transform, width, height):
        painter.beginNativePainting()
        try:
            if not self._ensure_resources() or not self._ensure_instancing_resources():
                return False
            if self.instancing_dirty:
                self._upload_instances()
            started = time.perf_counter()
            self.sprite_vertex_array.bind()
            self.sprite_program.bind()
            self.sprite_texture.bind(0)
            self.sprite_program.setUniformValue("u_atlas", 0)
            self.sprite_program.setUniformValue("u_transform", QVector4D(
                transform.m11(), transform.m12(), transform.m21(), transform.m22()))
            self.sprite_program.setUniformValue(
                "u_translate", QVector2D(transform.dx(), transform.dy()))
            self.sprite_program.setUniformValue(
                "u_viewport", QVector2D(float(width), float(height)))
            self.sprite_program.setUniformValue(
                "u_canvas_size", QVector2D(float(self.canvas.width), float(self.canvas.height)))
            self.last_instancing_time = max(
                0.0, time.perf_counter() - self._instancing_started)
            self.sprite_program.setUniformValue("u_time", self.last_instancing_time)
            self.sprite_program.setUniformValue(
                "u_animate", 1 if self.instancing_config.animate else 0)
            self.functions.glDisable(GL_SCISSOR_TEST)
            self.functions.glDisable(GL_STENCIL_TEST)
            self.functions.glEnable(GL_BLEND)
            self.functions.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            self.functions.glDrawArraysInstanced(
                GL_TRIANGLES, 0, 6, self.instancing_config.count)
            self.last_instancing_draw_calls = 1
            self.sprite_texture.release()
            self.sprite_program.release()
            self.sprite_vertex_array.release()
            self.canvas.profiler.record_ms(
                "instanced_draw_cpu", (time.perf_counter() - started) * 1000.0)
            self.last_instancing_error = ""
            return True
        except Exception as error:
            self.last_instancing_error = str(error)
            self.last_instancing_draw_calls = 0
            return False
        finally:
            painter.endNativePainting()

    def _ensure_lighting_resources(self):
        if self.light_mask_program is not None and self.light_program is not None:
            return True
        mask_program = QOpenGLShaderProgram()
        if not mask_program.addShaderFromSourceCode(
                QOpenGLShader.Vertex, LIGHT_MASK_VERTEX_SHADER):
            self.last_lighting_error = mask_program.log(); return False
        if not mask_program.addShaderFromSourceCode(
                QOpenGLShader.Fragment, LIGHT_MASK_FRAGMENT_SHADER):
            self.last_lighting_error = mask_program.log(); return False
        if not mask_program.link():
            self.last_lighting_error = mask_program.log(); return False
        light_program = QOpenGLShaderProgram()
        if not light_program.addShaderFromSourceCode(QOpenGLShader.Vertex,
                                                     POST_VERTEX_SHADER):
            self.last_lighting_error = light_program.log(); return False
        if not light_program.addShaderFromSourceCode(QOpenGLShader.Fragment,
                                                     LIGHT_FRAGMENT_SHADER):
            self.last_lighting_error = light_program.log(); return False
        if not light_program.link():
            self.last_lighting_error = light_program.log(); return False

        fan_buffer = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        fan_array = QOpenGLVertexArrayObject()
        quad_buffer = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        quad_array = QOpenGLVertexArrayObject()
        if (not fan_buffer.create() or not fan_array.create()
                or not quad_buffer.create() or not quad_array.create()):
            self.last_lighting_error = "无法创建光照 fan/fullscreen VAO/VBO"
            return False
        fan_array.bind(); fan_buffer.bind()
        fan_buffer.setUsagePattern(QOpenGLBuffer.DynamicDraw)
        mask_program.bind()
        position = mask_program.attributeLocation("a_position")
        mask_program.enableAttributeArray(position)
        mask_program.setAttributeBuffer(position, GL_FLOAT, 0, 2,
                                       LIGHT_VERTEX_STRIDE)
        mask_program.release(); fan_buffer.release(); fan_array.release()

        vertices = (
            -1.0, -1.0, 0.0, 0.0,  1.0, -1.0, 1.0, 0.0,
             1.0,  1.0, 1.0, 1.0, -1.0, -1.0, 0.0, 0.0,
             1.0,  1.0, 1.0, 1.0, -1.0,  1.0, 0.0, 1.0,
        )
        payload = struct.pack("<{}f".format(len(vertices)), *vertices)
        quad_array.bind(); quad_buffer.bind()
        quad_buffer.setUsagePattern(QOpenGLBuffer.StaticDraw)
        quad_buffer.allocate(payload, len(payload))
        light_program.bind()
        for name, offset in (("a_position", 0), ("a_uv", 8)):
            location = light_program.attributeLocation(name)
            light_program.enableAttributeArray(location)
            light_program.setAttributeBuffer(location, GL_FLOAT, offset, 2, 16)
        light_program.release(); quad_buffer.release(); quad_array.release()
        self.light_mask_program = mask_program
        self.light_program = light_program
        self.light_fan_buffer = fan_buffer
        self.light_fan_vertex_array = fan_array
        self.light_quad_buffer = quad_buffer
        self.light_quad_vertex_array = quad_array
        self.last_lighting_error = ""
        return True

    def _ensure_lighting_targets(self, width, height):
        size = (max(1, int(width)), max(1, int(height)))
        if (self.light_mask_target and self.light_target
                and self.light_mask_target.isValid() and self.light_target.isValid()
                and self.lighting_target_size == size):
            return True
        target_format = QOpenGLFramebufferObjectFormat()
        target_format.setAttachment(QOpenGLFramebufferObject.NoAttachment)
        target_format.setInternalTextureFormat(GL_RGBA8)
        target_format.setSamples(0)
        mask = QOpenGLFramebufferObject(size[0], size[1], target_format)
        light = QOpenGLFramebufferObject(size[0], size[1], target_format)
        if not mask.isValid() or not light.isValid():
            self.last_lighting_error = f"无法创建 {size[0]}×{size[1]} 光照 FBO"
            return False
        self.light_mask_target, self.light_target = mask, light
        self.lighting_target_size = size
        self.last_lighting_bytes = estimated_lighting_bytes(*size)
        return True

    def _upload_light_fan(self, frame):
        if self.light_fan_frame is not None and self.light_fan_frame.key == frame.key:
            return True
        self.light_fan_vertex_array.bind(); self.light_fan_buffer.bind()
        self.light_fan_buffer.allocate(frame.payload, len(frame.payload))
        self.light_fan_buffer.release(); self.light_fan_vertex_array.release()
        self.light_fan_frame = frame
        self.lighting_upload_count += 1
        return True

    def _draw_gpu_lighting(self, painter, snapshot, transform, width, height):
        frame = build_multi_light_fan(snapshot)
        valid_indexes = [index for index, item in enumerate(frame.ranges)
                         if item.vertex_count >= 5]
        if not valid_indexes:
            self.last_lighting_error = "所有 visibility polygon 均少于 3 个点"
            return False
        started = time.perf_counter()
        painter.beginNativePainting()
        try:
            if (not self._ensure_resources() or not self._ensure_lighting_resources()
                    or not self._ensure_lighting_targets(width, height)
                    or not self._upload_light_fan(frame)):
                return False
            config = snapshot.config
            self.functions.glDisable(GL_SCISSOR_TEST)
            self.functions.glDisable(GL_STENCIL_TEST)
            self.light_fan_vertex_array.bind(); self.light_fan_buffer.bind()
            self.light_mask_program.bind()
            self.light_mask_program.setUniformValue("u_transform", QVector4D(
                transform.m11(), transform.m12(), transform.m21(), transform.m22()))
            self.light_mask_program.setUniformValue(
                "u_translate", QVector2D(transform.dx(), transform.dy()))
            self.light_mask_program.setUniformValue(
                "u_viewport", QVector2D(float(width), float(height)))

            self.light_target.bind()
            self.functions.glViewport(0, 0, width, height)
            self.functions.glDisable(GL_BLEND)
            self.functions.glClearColor(config.ambient, config.ambient,
                                        config.ambient, 1.0)
            self.functions.glClear(GL_COLOR_BUFFER_BIT)
            self.light_quad_vertex_array.bind(); self.light_quad_buffer.bind()
            self.light_program.bind()
            self.light_program.setUniformValue("u_texture", 0)
            self.light_program.setUniformValue("u_stage", 0)
            self.light_program.setUniformValue("u_ambient", 0.0)
            self.light_program.setUniformValue(
                "u_viewport", QVector2D(float(width), float(height)))
            self.functions.glActiveTexture(GL_TEXTURE0)

            order = [index for index in valid_indexes
                     if index != config.selected_light]
            if config.selected_light in valid_indexes:
                order.append(config.selected_light)
            for light_index in order:
                fan_range = frame.ranges[light_index]
                source = snapshot.light_visibilities[light_index].source
                # The mask was sampled by the previous accumulation pass.
                # Detach it before rendering into the same texture again;
                # otherwise multi-light frames create an undefined feedback loop.
                self.functions.glBindTexture(GL_TEXTURE_2D, 0)
                self.light_mask_target.bind()
                self.functions.glViewport(0, 0, width, height)
                self.functions.glDisable(GL_BLEND)
                self.functions.glClearColor(0.0, 0.0, 0.0, 1.0)
                self.functions.glClear(GL_COLOR_BUFFER_BIT)
                self.light_fan_vertex_array.bind(); self.light_fan_buffer.bind()
                self.light_mask_program.bind()
                self.functions.glDrawArrays(
                    GL_TRIANGLE_FAN, fan_range.first_vertex, fan_range.vertex_count)

                device_x, device_y, radius = device_light_parameters(transform, source)
                color = QColor(source.color)
                self.light_target.bind()
                self.functions.glViewport(0, 0, width, height)
                self.functions.glEnable(GL_BLEND)
                self.functions.glBlendFunc(GL_ONE, GL_ONE)
                self.light_quad_vertex_array.bind(); self.light_quad_buffer.bind()
                self.light_program.bind()
                self.light_program.setUniformValue(
                    "u_light_device", QVector2D(device_x, height - device_y))
                self.light_program.setUniformValue("u_radius_device", radius)
                self.light_program.setUniformValue("u_intensity", source.intensity)
                self.light_program.setUniformValue("u_light_color", QVector3D(
                    color.redF(), color.greenF(), color.blueF()))
                self.functions.glBindTexture(
                    GL_TEXTURE_2D, self.light_mask_target.texture())
                self.functions.glDrawArrays(GL_TRIANGLES, 0, 6)

            QOpenGLFramebufferObject.bindDefault()
            self.functions.glViewport(0, 0, width, height)
            self.functions.glEnable(GL_BLEND)
            self.functions.glBlendFunc(GL_DST_COLOR, GL_ZERO)
            self.light_program.setUniformValue("u_stage", 1)
            self.functions.glBindTexture(GL_TEXTURE_2D, self.light_target.texture())
            self.functions.glDrawArrays(GL_TRIANGLES, 0, 6)
            self.functions.glBindTexture(GL_TEXTURE_2D, 0)
            self.light_program.release(); self.light_mask_program.release()
            self.light_fan_buffer.release(); self.light_fan_vertex_array.release()
            self.light_quad_buffer.release()
            self.light_quad_vertex_array.release()
            self.last_lighting_draw_calls = len(order) * 2 + 1
            self.lighting_active = True
            self.last_lighting_error = ""
            return True
        except Exception as error:
            self.last_lighting_error = str(error)
            self.lighting_active = False
            return False
        finally:
            self.last_lighting_ms = (time.perf_counter() - started) * 1000.0
            self.canvas.profiler.record_ms("gpu_lighting", self.last_lighting_ms)
            QOpenGLFramebufferObject.bindDefault()
            if self.functions:
                self.functions.glViewport(0, 0, width, height)
                self.functions.glEnable(GL_BLEND)
                self.functions.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            painter.endNativePainting()

    def _ensure_id_target(self, width, height):
        size = (max(1, int(width)), max(1, int(height)))
        if (self.id_target and self.id_target.isValid()
                and self.id_target_size == size):
            return True
        target_format = QOpenGLFramebufferObjectFormat()
        target_format.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
        target_format.setSamples(0)
        target_format.setInternalTextureFormat(GL_RGBA8)
        target = QOpenGLFramebufferObject(size[0], size[1], target_format)
        if not target.isValid():
            self.last_id_target_error = "无法创建 ID framebuffer object"
            return False
        self.id_target = target
        self.id_target_size = size
        self.last_id_target_error = ""
        return True

    def _render_id_target(self, painter, frame, transform, width, height):
        """Render UUID ownership into an offscreen RGBA8 attachment."""
        painter.beginNativePainting()
        try:
            if not self._ensure_resources() or not self._ensure_id_target(width, height):
                return False
            self.id_target.bind()
            self.functions.glViewport(0, 0, width, height)
            self.functions.glDisable(GL_BLEND)
            self.functions.glDisable(GL_MULTISAMPLE)
            self.functions.glDisable(GL_SCISSOR_TEST)
            self.functions.glDisable(GL_STENCIL_TEST)
            self.functions.glClearColor(0.0, 0.0, 0.0, 0.0)
            self.functions.glClear(GL_COLOR_BUFFER_BIT | GL_STENCIL_BUFFER_BIT)
            self.vertex_array.bind()
            self.vertex_buffer.bind()
            self.program.bind()
            self.program.setUniformValue("u_transform", QVector4D(
                transform.m11(), transform.m12(), transform.m21(), transform.m22()))
            self.program.setUniformValue("u_translate", QVector2D(
                transform.dx(), transform.dy()))
            self.program.setUniformValue("u_viewport", QVector2D(float(width), float(height)))
            self.program.setUniformValue("u_shader_mode", 0)
            self.program.setUniformValue("u_time", 0.0)
            self.program.setUniformValue("u_pick_mode", 1)

            shape_by_id = {shape.id: shape for shape in self.canvas.shapes}
            ordered_pickable = []
            for shape_id in self.cache.ordered_shape_ids:
                shape = shape_by_id.get(shape_id)
                if (shape is not None
                        and not self.canvas.layer_manager.is_shape_locked(shape)):
                    ordered_pickable.append(shape_id)
            # A deterministic multiplicative permutation keeps IDs unique for the
            # bounded 24-bit space while making the attachment preview visible.
            shape_to_pick = {shape_id: ((index + 1) * 0x9E3779) & 0xFFFFFF
                             for index, shape_id in enumerate(ordered_pickable)}
            self.pick_id_to_shape = {value: key for key, value in shape_to_pick.items()}
            viewport = frame.viewport
            for shape_id, primitive_index, primitive in self.cache.primitive_items(viewport):
                pick_id = shape_to_pick.get(shape_id)
                allocation = self.arena.allocations.get((shape_id, primitive_index))
                if not pick_id or allocation is None or not allocation.vertex_count:
                    continue
                red, green, blue, alpha = encode_pick_id(pick_id)
                self.program.setUniformValue(
                    "u_pick_color", QVector4D(red / 255.0, green / 255.0,
                                               blue / 255.0, alpha / 255.0))
                self.functions.glDrawArrays(
                    GL_TRIANGLES, allocation.first_vertex, allocation.vertex_count)

            self.program.setUniformValue("u_pick_mode", 0)
            self.program.release()
            self.vertex_buffer.release()
            self.vertex_array.release()
            self.last_id_target_revision = self.cache.revision
            return True
        except Exception as error:
            self.last_id_target_error = str(error)
            return False
        finally:
            QOpenGLFramebufferObject.bindDefault()
            self.functions.glViewport(0, 0, width, height)
            self.functions.glEnable(GL_MULTISAMPLE)
            self.functions.glEnable(GL_BLEND)
            self.functions.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            painter.endNativePainting()

    def pick_device_pixel(self, x, y):
        """Read exactly one ID pixel. A current matching context is required."""
        if (not self.id_target or not self.id_target.isValid()
                or self.last_id_target_revision != self.cache.revision):
            return None, 0.0, "ID target 尚未生成或已经过期"
        width, height = self.id_target_size
        x, y = int(x), int(y)
        if x < 0 or y < 0 or x >= width or y >= height:
            return None, 0.0, "点击位置位于 ID target 之外"
        started = time.perf_counter()
        pixel = (ctypes.c_ubyte * 4)()
        try:
            self.id_target.bind()
            self.functions.glReadPixels(
                x, height - 1 - y, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE,
                ctypes.cast(pixel, ctypes.c_void_p))
            pick_id = decode_pick_id(pixel[0], pixel[1], pixel[2])
            shape_id = self.pick_id_to_shape.get(pick_id)
            return shape_id, (time.perf_counter() - started) * 1000.0, ""
        except Exception as error:
            return None, (time.perf_counter() - started) * 1000.0, str(error)
        finally:
            QOpenGLFramebufferObject.bindDefault()

    def id_attachment_image(self):
        if not self.id_target or not self.id_target.isValid():
            return None
        return self.id_target.toImage()

    def _ensure_post_resources(self):
        if self.post_program is not None:
            return True
        program = QOpenGLShaderProgram()
        if not program.addShaderFromSourceCode(QOpenGLShader.Vertex, POST_VERTEX_SHADER):
            self.last_offscreen_error = program.log()
            return False
        if not program.addShaderFromSourceCode(QOpenGLShader.Fragment, POST_FRAGMENT_SHADER):
            self.last_offscreen_error = program.log()
            return False
        if not program.link():
            self.last_offscreen_error = program.log()
            return False
        vertices = (
            -1.0, -1.0, 0.0, 0.0,  1.0, -1.0, 1.0, 0.0,
             1.0,  1.0, 1.0, 1.0, -1.0, -1.0, 0.0, 0.0,
             1.0,  1.0, 1.0, 1.0, -1.0,  1.0, 0.0, 1.0,
        )
        payload = struct.pack("<{}f".format(len(vertices)), *vertices)
        buffer = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        vertex_array = QOpenGLVertexArrayObject()
        if not buffer.create() or not vertex_array.create():
            self.last_offscreen_error = "无法创建 fullscreen quad buffer/VAO"
            return False
        vertex_array.bind()
        buffer.bind()
        buffer.setUsagePattern(QOpenGLBuffer.StaticDraw)
        buffer.allocate(payload, len(payload))
        program.bind()
        position = program.attributeLocation("a_position")
        uv = program.attributeLocation("a_uv")
        program.enableAttributeArray(position)
        program.setAttributeBuffer(position, GL_FLOAT, 0, 2, 16)
        program.enableAttributeArray(uv)
        program.setAttributeBuffer(uv, GL_FLOAT, 8, 2, 16)
        program.release()
        buffer.release()
        vertex_array.release()
        self.post_program = program
        self.post_buffer = buffer
        self.post_vertex_array = vertex_array
        return True

    def _ensure_color_targets(self, width, height):
        size = (int(width), int(height))
        if (self.color_target and self.post_target
                and self.color_target.isValid() and self.post_target.isValid()
                and self.offscreen_target_size == size):
            return True
        source_format = QOpenGLFramebufferObjectFormat()
        source_format.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
        source_format.setInternalTextureFormat(GL_RGBA8)
        source_format.setSamples(0)
        destination_format = QOpenGLFramebufferObjectFormat()
        destination_format.setAttachment(QOpenGLFramebufferObject.NoAttachment)
        destination_format.setInternalTextureFormat(GL_RGBA8)
        destination_format.setSamples(0)
        source = QOpenGLFramebufferObject(width, height, source_format)
        destination = QOpenGLFramebufferObject(width, height, destination_format)
        if not source.isValid() or not destination.isValid():
            self.last_offscreen_error = f"无法创建 {width}×{height} color/postprocess FBO"
            return False
        self.color_target, self.post_target = source, destination
        self.offscreen_target_size = size
        self.last_offscreen_bytes = estimated_target_bytes(width, height)
        return True

    def render_offscreen_attachment(self, effect="none", scale=1,
                                    attachment="postprocess"):
        """Run a manual two-pass render and return a readback QImage."""
        effect = validate_postprocess(effect)
        attachment = validate_attachment_view(attachment)
        if attachment == "id":
            image = self.id_attachment_image()
            if image is None:
                self.last_offscreen_error = "ID attachment 尚未生成"
            return image
        if (self.context is None or QOpenGLContext.currentContext() is not self.context):
            self.last_offscreen_error = "离屏渲染需要当前 OpenGL context"
            return None
        if self._last_frame is None or self._last_transform is None:
            self.last_offscreen_error = "尚无可复用的 OpenGL frame"
            return None
        try:
            width, height = offscreen_dimensions(
                self._last_device_size[0], self._last_device_size[1], scale)
        except ValueError as error:
            self.last_offscreen_error = str(error)
            return None
        started = time.perf_counter()
        try:
            if (not self._ensure_resources() or not self._ensure_post_resources()
                    or not self._ensure_color_targets(width, height)):
                return None
            scale_x = width / max(1, self._last_device_size[0])
            scale_y = height / max(1, self._last_device_size[1])
            transform = self._last_transform

            self.color_target.bind()
            self.functions.glViewport(0, 0, width, height)
            self.functions.glDisable(GL_SCISSOR_TEST)
            self.functions.glDisable(GL_STENCIL_TEST)
            self.functions.glClearColor(1.0, 1.0, 1.0, 1.0)
            self.functions.glClear(GL_COLOR_BUFFER_BIT | GL_STENCIL_BUFFER_BIT)
            if self.experiment.blend_mode == "opaque":
                self.functions.glDisable(GL_BLEND)
            else:
                self.functions.glEnable(GL_BLEND)
                destination = (GL_ONE if self.experiment.blend_mode == "additive"
                               else GL_ONE_MINUS_SRC_ALPHA)
                self.functions.glBlendFunc(GL_SRC_ALPHA, destination)
            self.vertex_array.bind()
            self.vertex_buffer.bind()
            self.program.bind()
            self.program.setUniformValue("u_transform", QVector4D(
                transform.m11() * scale_x, transform.m12() * scale_y,
                transform.m21() * scale_x, transform.m22() * scale_y))
            self.program.setUniformValue("u_translate", QVector2D(
                transform.dx() * scale_x, transform.dy() * scale_y))
            self.program.setUniformValue("u_viewport", QVector2D(float(width), float(height)))
            shader_index = {
                "vertex_color": 0, "screen_gradient": 1,
                "time_pulse": 2, "coverage": 3,
            }[self.experiment.shader_mode]
            self.program.setUniformValue("u_shader_mode", shader_index)
            self.program.setUniformValue("u_time", self.last_time_uniform)
            self.program.setUniformValue("u_pick_mode", 0)
            self.program.setUniformValue("u_pick_color", QVector4D(0.0, 0.0, 0.0, 0.0))
            for batch in self._last_frame.batches:
                self.functions.glDrawArrays(
                    GL_TRIANGLES, batch.first_vertex, batch.vertex_count)
            self.program.release()
            self.vertex_buffer.release()
            self.vertex_array.release()

            self.post_target.bind()
            self.functions.glViewport(0, 0, width, height)
            self.functions.glDisable(GL_BLEND)
            self.functions.glClearColor(0.0, 0.0, 0.0, 0.0)
            self.functions.glClear(GL_COLOR_BUFFER_BIT)
            self.post_vertex_array.bind()
            self.post_buffer.bind()
            self.post_program.bind()
            effect_index = {"none": 0, "grayscale": 1, "invert": 2, "edge": 3}[effect]
            self.post_program.setUniformValue("u_texture", 0)
            self.post_program.setUniformValue("u_effect", effect_index)
            self.post_program.setUniformValue(
                "u_texel_size", QVector2D(1.0 / width, 1.0 / height))
            self.functions.glActiveTexture(GL_TEXTURE0)
            self.functions.glBindTexture(GL_TEXTURE_2D, self.color_target.texture())
            self.functions.glDrawArrays(GL_TRIANGLES, 0, 6)
            self.functions.glBindTexture(GL_TEXTURE_2D, 0)
            self.post_program.release()
            self.post_buffer.release()
            self.post_vertex_array.release()
            QOpenGLFramebufferObject.bindDefault()
            image = (self.color_target.toImage() if attachment == "color"
                     else self.post_target.toImage())
            self.last_offscreen_effect = effect
            self.last_offscreen_error = ""
            return image
        except Exception as error:
            self.last_offscreen_error = str(error)
            return None
        finally:
            self.last_offscreen_ms = (time.perf_counter() - started) * 1000.0
            QOpenGLFramebufferObject.bindDefault()
            main_width, main_height = self._last_device_size
            if self.functions:
                self.functions.glViewport(0, 0, main_width, main_height)
                self.functions.glEnable(GL_MULTISAMPLE)
                self.functions.glEnable(GL_BLEND)
                self.functions.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    @staticmethod
    def _draw_text(painter, command):
        if len(command.local_rect) < 3:
            return
        transform = command.transform
        painter.save()
        painter.setTransform(QTransform(transform[0], transform[1], transform[2],
                                        transform[3], transform[4], transform[5]), True)
        painter.setPen(QPen(QColor.fromRgbF(*command.color)))
        font = QFont(painter.font()); font.setPointSizeF(command.font_size); painter.setFont(font)
        first, third = command.local_rect[0], command.local_rect[2]
        rect = QRectF(QPointF(*first), QPointF(*third)).normalized()
        painter.drawText(rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, command.text)
        painter.restore()
