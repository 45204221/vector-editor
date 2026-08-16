"""图形视图控件"""

import time

from PyQt5.QtWidgets import (QGraphicsView, QGraphicsScene, QGraphicsItem,
                             QOpenGLWidget, QWidget)
from PyQt5.QtCore import Qt, QRectF, QPointF, pyqtSignal, QTimer
from PyQt5.QtGui import (QWheelEvent, QMouseEvent, QKeyEvent, QPainter, QPen,
                         QColor, QBrush, QSurfaceFormat)

from core.canvas import Canvas
from core.selection import SelectionMode
from tools.tool_manager import ToolManager
from core.rendering import CommandQPainterBackend, QPainterBackend, RenderDirtyFlag
from core.opengl_backend import OpenGLBackend
from core.pipeline_debug import (PipelineDebugMode, build_pipeline_snapshot,
                                 draw_pipeline_overlay)
from core.native_geometry import backend_name as geometry_backend_name
from core.raster_experiments import RasterExperimentConfig
from core.offscreen_experiments import (PickComparison, validate_attachment_view,
                                        validate_picking_mode, validate_postprocess)
from core.instancing_experiment import InstancingConfig
from core.glyph_atlas import GpuTextConfig
from core.lighting_experiment import (MAX_LIGHTS, LightSource, LightingConfig,
                                      build_lighting_snapshot, draw_lighting_debug,
                                      rebind_lighting_snapshot)


class GraphicsView(QGraphicsView):
    """图形视图控件 — 模拟 MSPaint 风格的固定画布"""

    viewport_changed = pyqtSignal()
    zoom_changed = pyqtSignal(float)
    pan_mode_changed = pyqtSignal(bool)
    render_backend_status_changed = pyqtSignal(str)
    pipeline_snapshot_changed = pyqtSignal()
    raster_experiment_changed = pyqtSignal()
    offscreen_experiment_changed = pyqtSignal()
    instancing_experiment_changed = pyqtSignal()
    gpu_text_experiment_changed = pyqtSignal()
    lighting_experiment_changed = pyqtSignal()

    def __init__(self, canvas: Canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.setRenderHint(QPainter.Antialiasing)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

        # 视图默认无拖拽模式
        self.setDragMode(QGraphicsView.NoDrag)
        # 滚动条：仅在需要时出现
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.zoom_factor = 1.0
        self.min_zoom = 0.1
        self.max_zoom = 10.0
        self.zoom_step = 1.2

        self.pan_mode = False
        self.multi_select_mode = False

        # 场景 — 固定尺寸，灰色背景（模拟 MSPaint 画布外的区域）
        self.scene = QGraphicsScene()
        self.scene.setSceneRect(0, 0, self.canvas.width, self.canvas.height)
        self.scene.setBackgroundBrush(QBrush(QColor(128, 128, 128)))
        self.setScene(self.scene)

        # 渲染项：覆盖整个画布，绘制白色背景 + 网格 + 图形
        self.render_item = SceneRenderItem(self.canvas)
        self.render_item.status_callback = (
            lambda: self.render_backend_status_changed.emit(self.render_backend_status()))
        self.scene.addItem(self.render_item)

        # 工具管理器
        self.tool_manager = ToolManager(self)
        self.physics_timer = QTimer(self)
        self.physics_timer.setInterval(16)
        self.physics_timer.timeout.connect(self.canvas.physics_step)
        self.raster_experiment = RasterExperimentConfig()
        self.shader_timer = QTimer(self)
        self.shader_timer.setInterval(33)
        self.shader_timer.timeout.connect(self.scene.update)
        self.picking_mode = "cpu"
        self.postprocess_mode = "none"
        self.attachment_view = "postprocess"
        self.offscreen_scale = 1
        self.instancing_config = InstancingConfig()
        self.gpu_text_config = GpuTextConfig()
        self.lighting_config = LightingConfig(
            light_x=self.canvas.width / 2, light_y=self.canvas.height / 2)
        self._lighting_cache_key = None
        self._lighting_snapshot = None
        self._lighting_build_count = 0
        self._lighting_cache_hits = 0
        self._dragging_light = False
        self.render_item.lighting_snapshot_provider = self.lighting_snapshot
        self.sprite_timer = QTimer(self)
        self.sprite_timer.setInterval(33)
        self.sprite_timer.timeout.connect(self.scene.update)

        # 信号连接
        self.canvas.canvas_changed.connect(self.scene.update)
        self.canvas.selection_changed.connect(self.scene.update)
        self.canvas.preview_changed.connect(self.scene.update)

        # 初始显示：让画布适配窗口
        self.fit_to_window()

    def update_scene(self) -> None:
        self.scene.update()

    def update_selection(self) -> None:
        self.scene.update()

    def fit_to_window(self) -> None:
        """将完整画布缩放至适配窗口"""
        self.fitInView(QRectF(0, 0, self.canvas.width, self.canvas.height), Qt.KeepAspectRatio)
        self.zoom_factor = self.transform().m11()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y() / 120
            if delta > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    def zoom_in(self) -> None:
        new_zoom = self.zoom_factor * self.zoom_step
        if new_zoom <= self.max_zoom:
            self.zoom_factor = new_zoom
            self.scale(self.zoom_step, self.zoom_step)
            self.zoom_changed.emit(self.zoom_factor)

    def zoom_out(self) -> None:
        new_zoom = self.zoom_factor / self.zoom_step
        if new_zoom >= self.min_zoom:
            self.zoom_factor = new_zoom
            self.scale(1 / self.zoom_step, 1 / self.zoom_step)
            self.zoom_changed.emit(self.zoom_factor)

    def set_zoom(self, factor: float) -> None:
        factor = max(self.min_zoom, min(self.max_zoom, factor))
        if factor != self.zoom_factor:
            self.scale(factor / self.zoom_factor, factor / self.zoom_factor)
            self.zoom_factor = factor
            self.zoom_changed.emit(self.zoom_factor)

    def reset_zoom(self) -> None:
        self.set_zoom(1.0)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self.lighting_config.enabled and event.button() == Qt.LeftButton:
            point = self.mapToScene(event.pos())
            source = self.lighting_config.selected_source()
            dx = point.x() - source.x
            dy = point.y() - source.y
            threshold = 14.0 / max(0.05, abs(self.transform().m11()))
            if dx * dx + dy * dy <= threshold * threshold:
                self._dragging_light = True
                self.viewport().setCursor(Qt.ClosedHandCursor)
                event.accept()
                return
        try:
            self.tool_manager.mousePressEvent(event)
        except Exception as e:
            print(f"Error in tool mousePressEvent: {e}")
        if self.get_current_tool() == 'select':
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging_light:
            point = self.mapToScene(event.pos())
            self.set_selected_light_parameters(x=point.x(), y=point.y())
            event.accept()
            return
        try:
            self.tool_manager.mouseMoveEvent(event)
        except Exception as e:
            print(f"Error in tool mouseMoveEvent: {e}")
        if self.get_current_tool() == 'select':
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._dragging_light and event.button() == Qt.LeftButton:
            self._dragging_light = False
            self.viewport().setCursor(Qt.ArrowCursor)
            event.accept()
            return
        try:
            self.tool_manager.mouseReleaseEvent(event)
        except Exception as e:
            print(f"Error in tool mouseReleaseEvent: {e}")
        if self.get_current_tool() == 'select':
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.tool_manager.mouseDoubleClickEvent(event)
        if self.get_current_tool() == 'select':
            super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Space:
            self.pan_mode = not self.pan_mode
            self.pan_mode_changed.emit(self.pan_mode)
            self.viewport().setCursor(Qt.OpenHandCursor if self.pan_mode else Qt.ArrowCursor)
            event.accept()
        elif event.key() == Qt.Key_Delete:
            if self.canvas.get_selected_shapes():
                self.canvas.delete_selected_shapes()
            event.accept()
        elif event.key() == Qt.Key_Control:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            event.accept()
        elif event.key() == Qt.Key_F:
            self.fit_to_window()
            event.accept()
        elif event.key() == Qt.Key_Plus or event.key() == Qt.Key_Equal:
            self.zoom_in()
            event.accept()
        elif event.key() == Qt.Key_Minus:
            self.zoom_out()
            event.accept()
        elif event.key() == Qt.Key_0:
            self.reset_zoom()
            event.accept()
        elif event.key() == Qt.Key_Escape:
            current_tool = self.tool_manager.current_tool
            if current_tool:
                current_tool.deactivate()
                current_tool.activate()
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Control:
            if self.get_current_tool() == 'select':
                self.setDragMode(QGraphicsView.RubberBandDrag)
            else:
                self.setDragMode(QGraphicsView.NoDrag)
            event.accept()
        else:
            super().keyReleaseEvent(event)

    def set_tool(self, tool_name: str) -> None:
        self.tool_manager.set_tool(tool_name)
        if tool_name == 'select':
            self.setDragMode(QGraphicsView.RubberBandDrag)
        else:
            self.setDragMode(QGraphicsView.NoDrag)
            self.multi_select_mode = False

    def set_physics_running(self, running: bool) -> None:
        self.canvas.physics_world.running = running
        if running: self.physics_timer.start()
        else: self.physics_timer.stop()

    def set_command_rendering(self, enabled: bool) -> None:
        self.set_render_backend("command" if enabled else "legacy")

    def set_render_backend(self, backend_name: str) -> None:
        backend_name = backend_name.lower()
        old_viewport = self.viewport()
        if backend_name == "opengl":
            if not isinstance(old_viewport, QOpenGLWidget):
                viewport_widget = QOpenGLWidget()
                surface_format = QSurfaceFormat.defaultFormat()
                surface_format.setSamples(max(4, surface_format.samples()))
                surface_format.setStencilBufferSize(
                    max(8, surface_format.stencilBufferSize()))
                viewport_widget.setFormat(surface_format)
                self.setViewport(viewport_widget)
            self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
            backend = OpenGLBackend(self.canvas, self.raster_experiment)
            backend.set_picking_mode(self.picking_mode)
            backend.set_instancing_config(self.instancing_config)
            backend.set_gpu_text_config(self.gpu_text_config)
        else:
            backend = CommandQPainterBackend(self.canvas) if backend_name == "command" else QPainterBackend()
            if isinstance(old_viewport, QOpenGLWidget):
                try:
                    old_viewport.makeCurrent()
                    self.render_item.backend.release()
                    old_viewport.doneCurrent()
                except Exception:
                    pass
                self.setViewport(QWidget())
            self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.viewport().setMouseTracking(True)
        self.render_item.set_backend(backend)
        self._update_shader_timer()
        self._update_sprite_timer()
        self.scene.update()
        self.pipeline_snapshot_changed.emit()
        self.raster_experiment_changed.emit()
        self.offscreen_experiment_changed.emit()
        self.instancing_experiment_changed.emit()
        self.gpu_text_experiment_changed.emit()
        self.lighting_experiment_changed.emit()

    def set_raster_experiment(self, shader_mode=None, blend_mode=None,
                              clip_mode=None) -> None:
        """Change runtime GL state without touching the document/history."""
        updated = self.raster_experiment.changed(shader_mode, blend_mode, clip_mode)
        if updated == self.raster_experiment:
            return
        self.raster_experiment = updated
        backend = self.render_item.backend
        if isinstance(backend, OpenGLBackend):
            backend.set_experiment(updated)
        self._update_shader_timer()
        self.scene.update()
        self.pipeline_snapshot_changed.emit()
        self.raster_experiment_changed.emit()

    def reset_raster_experiment(self) -> None:
        defaults = RasterExperimentConfig()
        self.set_raster_experiment(defaults.shader_mode, defaults.blend_mode,
                                   defaults.clip_mode)

    def _update_shader_timer(self) -> None:
        animate = (isinstance(self.render_item.backend, OpenGLBackend) and
                   self.raster_experiment.shader_mode == "time_pulse")
        if animate:
            self.shader_timer.start()
        else:
            self.shader_timer.stop()

    def raster_experiment_state(self):
        backend = self.render_item.backend
        if isinstance(backend, OpenGLBackend):
            return backend.experiment_state()
        state = self.raster_experiment.as_dict()
        state.update({
            "effective_clip_mode": "inactive",
            "stencil_bits": 0,
            "time_uniform": 0.0,
            "active": False,
            "warning": "实验配置已保留；切换到 OpenGL 后端后生效。",
        })
        return state

    def set_picking_mode(self, mode) -> None:
        mode = validate_picking_mode(mode)
        if mode == self.picking_mode:
            return
        self.picking_mode = mode
        backend = self.render_item.backend
        if isinstance(backend, OpenGLBackend):
            backend.set_picking_mode(mode)
        self.scene.update()
        self.pipeline_snapshot_changed.emit()
        self.offscreen_experiment_changed.emit()

    def offscreen_experiment_state(self):
        backend = self.render_item.backend
        if isinstance(backend, OpenGLBackend):
            return backend.offscreen_state()
        return {
            "picking_mode": self.picking_mode,
            "target_size": (0, 0), "target_valid": False,
            "target_revision": -1,
            "attachment": "RGBA8 object ID + CombinedDepthStencil",
            "mapped_shapes": 0, "cpu_shape_id": "", "gpu_shape_id": "",
            "cpu_ms": 0.0, "gpu_ms": 0.0, "matched": True,
            "gpu_available": False,
            "warning": "当前后端不是 OpenGL，选择自动使用 CPU。",
            "color_target_size": (0, 0), "color_target_valid": False,
            "post_target_valid": False, "postprocess_effect": self.postprocess_mode,
            "offscreen_ms": 0.0, "offscreen_bytes": 0,
            "offscreen_error": "当前后端不是 OpenGL。",
        }

    def set_offscreen_preview_config(self, effect=None, attachment=None, scale=None):
        if effect is not None:
            self.postprocess_mode = validate_postprocess(effect)
        if attachment is not None:
            self.attachment_view = validate_attachment_view(attachment)
        if scale is not None:
            scale = int(scale)
            if scale not in (1, 2):
                raise ValueError("offscreen scale must be 1 or 2")
            self.offscreen_scale = scale
        self.offscreen_experiment_changed.emit()

    def render_offscreen_attachment(self):
        backend = self.render_item.backend
        viewport = self.viewport()
        if not isinstance(backend, OpenGLBackend) or not hasattr(viewport, "makeCurrent"):
            return None
        try:
            viewport.makeCurrent()
            return backend.render_offscreen_attachment(
                self.postprocess_mode, self.offscreen_scale, self.attachment_view)
        finally:
            viewport.doneCurrent()

    def set_instancing_experiment(self, enabled=None, count=None, sprite_mode=None,
                                  animate=None, seed=None):
        changes = {}
        for name, value in (("enabled", enabled), ("count", count),
                            ("sprite_mode", sprite_mode), ("animate", animate),
                            ("seed", seed)):
            if value is not None:
                changes[name] = value
        updated = self.instancing_config.changed(**changes)
        if updated == self.instancing_config:
            return
        self.instancing_config = updated
        backend = self.render_item.backend
        if isinstance(backend, OpenGLBackend):
            backend.set_instancing_config(updated)
        self._update_sprite_timer()
        self.scene.update()
        self.instancing_experiment_changed.emit()

    def reset_instancing_seed(self):
        self.set_instancing_experiment(seed=self.instancing_config.seed + 1)

    def _update_sprite_timer(self):
        active = (isinstance(self.render_item.backend, OpenGLBackend)
                  and self.instancing_config.enabled
                  and self.instancing_config.animate)
        if active:
            self.sprite_timer.start()
        else:
            self.sprite_timer.stop()

    def instancing_experiment_state(self):
        backend = self.render_item.backend
        if isinstance(backend, OpenGLBackend):
            return backend.instancing_state()
        return {
            "enabled": self.instancing_config.enabled,
            "count": self.instancing_config.count,
            "sprite_mode": self.instancing_config.sprite_mode,
            "animate": self.instancing_config.animate,
            "seed": self.instancing_config.seed,
            "resources_valid": False, "atlas_size": (192, 64),
            "instance_bytes": self.instancing_config.count * 56,
            "upload_count": 0, "draw_calls": 0, "time_uniform": 0.0,
            "error": "切换到 OpenGL 后端后生效。",
        }

    def set_gpu_text_experiment(self, enabled=None, show_demo=None):
        changes = {}
        if enabled is not None:
            changes["enabled"] = bool(enabled)
        if show_demo is not None:
            changes["show_demo"] = bool(show_demo)
        updated = self.gpu_text_config.changed(**changes)
        if updated == self.gpu_text_config:
            return
        self.gpu_text_config = updated
        backend = self.render_item.backend
        if isinstance(backend, OpenGLBackend):
            backend.set_gpu_text_config(updated)
        self.scene.update()
        self.pipeline_snapshot_changed.emit()
        self.gpu_text_experiment_changed.emit()

    def gpu_text_experiment_state(self):
        backend = self.render_item.backend
        if isinstance(backend, OpenGLBackend):
            return backend.gpu_text_state()
        return {
            "enabled": self.gpu_text_config.enabled,
            "show_demo": self.gpu_text_config.show_demo,
            "resources_valid": False, "atlas_size": (1024, 1024),
            "atlas_bytes": 4 * 1024 * 1024, "unique_glyphs": 0,
            "rendered_glyphs": 0, "vertices": 0, "vbo_bytes": 0,
            "draw_calls": 0, "upload_count": 0, "atlas_rebuild_count": 0,
            "fallback_commands": 0,
            "error": "切换到 OpenGL 后端后生效。",
        }

    def set_lighting_experiment(self, **changes):
        changes = {name: value for name, value in changes.items() if value is not None}
        updated = self.lighting_config.changed(**changes)
        if updated == self.lighting_config:
            return
        self.lighting_config = updated
        self.scene.update()
        self.lighting_experiment_changed.emit()

    def set_selected_light_parameters(self, x=None, y=None, radius=None,
                                      intensity=None, color=None):
        config = self.lighting_config
        index = config.selected_light
        source = config.selected_source()
        changes = {name: value for name, value in (
            ("x", x), ("y", y), ("radius", radius),
            ("intensity", intensity), ("color", color)) if value is not None}
        updated_source = source.changed(**changes)
        if updated_source == source:
            return
        if index == 0:
            self.set_lighting_experiment(
                light_x=updated_source.x, light_y=updated_source.y,
                radius=updated_source.radius, intensity=updated_source.intensity,
                color=updated_source.color)
        else:
            extras = list(config.extra_lights)
            extras[index - 1] = updated_source
            self.set_lighting_experiment(extra_lights=tuple(extras))

    def select_lighting_source(self, index):
        index = int(index)
        if not 0 <= index < len(self.lighting_config.light_sources()):
            raise ValueError("selected light index is out of range")
        self.set_lighting_experiment(selected_light=index)

    def add_lighting_source(self):
        config = self.lighting_config
        sources = config.light_sources()
        if len(sources) >= MAX_LIGHTS:
            return False
        anchor = config.selected_source()
        colors = ("#68B8FF", "#FF6B6B", "#9BFF8A", "#C48CFF")
        source = LightSource(
            anchor.x + 120.0, anchor.y + 80.0, anchor.radius,
            anchor.intensity, colors[len(sources) % len(colors)])
        extras = config.extra_lights + (source,)
        self.set_lighting_experiment(
            extra_lights=extras, selected_light=len(sources))
        return True

    def remove_selected_lighting_source(self):
        config = self.lighting_config
        if config.selected_light == 0:
            return False
        extras = list(config.extra_lights)
        extras.pop(config.selected_light - 1)
        self.set_lighting_experiment(
            extra_lights=tuple(extras),
            selected_light=min(config.selected_light - 1, len(extras)))
        return True

    def lighting_snapshot(self):
        if not self.lighting_config.enabled:
            return None
        config = self.lighting_config
        positions = tuple((source.x, source.y) for source in config.light_sources())
        key = (self.canvas.render_revision, positions, config.angle_epsilon,
               config.use_native,
               id(self.render_item.backend))
        if key != self._lighting_cache_key:
            self._lighting_snapshot = build_lighting_snapshot(
                self.canvas, self.render_item.backend, config)
            self._lighting_cache_key = key
            self._lighting_build_count += 1
        elif self._lighting_snapshot.config != config:
            self._lighting_snapshot = rebind_lighting_snapshot(
                self._lighting_snapshot, config)
            self._lighting_cache_hits += 1
        self.canvas.profiler.set_gauge(
            "visibility_build_count", self._lighting_build_count)
        self.canvas.profiler.set_gauge(
            "visibility_cache_hits", self._lighting_cache_hits)
        return self._lighting_snapshot

    def lighting_experiment_state(self):
        config = self.lighting_config
        source = config.selected_source()
        snapshot = self.lighting_snapshot()
        if snapshot is None:
            state = {
                "enabled": config.enabled, "light_x": source.x,
                "light_y": source.y, "radius": source.radius,
                "intensity": source.intensity, "ambient": config.ambient,
                "color": source.color, "debug_mode": config.debug_mode,
                "use_native": config.use_native,
                "gpu_lighting": config.gpu_lighting, "backend": "未运行",
                "revision": self.canvas.render_revision, "build_ms": 0.0,
                "segments": 0, "rays": 0, "polygon_points": 0,
                "intersection_tests": 0, "truncated": False, "warning": "",
                "light_count": len(config.light_sources()),
                "selected_light": config.selected_light,
                "visibility_build_count": self._lighting_build_count,
                "visibility_cache_hits": self._lighting_cache_hits,
            }
            state.update(self._gpu_lighting_state())
            return state
        result = snapshot.result
        state = {
            "enabled": config.enabled, "light_x": source.x,
            "light_y": source.y, "radius": source.radius,
            "intensity": source.intensity, "ambient": config.ambient,
            "color": source.color, "debug_mode": config.debug_mode,
            "use_native": config.use_native,
            "gpu_lighting": config.gpu_lighting, "backend": result.backend,
            "revision": snapshot.source_revision, "build_ms": snapshot.build_ms,
            "segments": len(snapshot.segments),
            "rays": sum(len(item.result.rays) for item in snapshot.light_visibilities),
            "polygon_points": len(result.polygon),
            "intersection_tests": sum(item.result.intersection_tests
                                      for item in snapshot.light_visibilities),
            "truncated": snapshot.truncated,
            "warning": result.error,
            "light_count": len(snapshot.light_visibilities),
            "selected_light": config.selected_light,
            "visibility_build_count": self._lighting_build_count,
            "visibility_cache_hits": self._lighting_cache_hits,
        }
        state.update(self._gpu_lighting_state())
        return state

    def _gpu_lighting_state(self):
        backend = self.render_item.backend
        if isinstance(backend, OpenGLBackend):
            return backend.lighting_state()
        return {
            "gpu_supported": False,
            "gpu_requested": self.lighting_config.gpu_lighting,
            "gpu_active": False, "target_size": (0, 0),
            "light_count": len(self.lighting_config.light_sources()),
            "mask_valid": False, "light_valid": False,
            "fbo_bytes": 0, "fan_vertices": 0, "fan_vbo_bytes": 0,
            "upload_count": 0, "draw_calls": 0, "pass_ms": 0.0,
            "error": "GPU 光照仅在 OpenGL 后端生效。",
        }

    def render_lighting_attachment(self, attachment):
        backend = self.render_item.backend
        viewport = self.viewport()
        if not isinstance(backend, OpenGLBackend) or not hasattr(viewport, "makeCurrent"):
            return None
        try:
            viewport.makeCurrent()
            return backend.lighting_attachment_image(attachment)
        finally:
            viewport.doneCurrent()

    def hit_test_for_selection(self, scene_pos, viewport_pos):
        """Keep CPU authoritative unless the explicit GPU experiment is active."""
        started = time.perf_counter()
        cpu_shape = self.canvas.hit_test(scene_pos)
        cpu_ms = (time.perf_counter() - started) * 1000.0
        if self.picking_mode == "cpu":
            return cpu_shape
        backend = self.render_item.backend
        if not isinstance(backend, OpenGLBackend):
            return cpu_shape
        gpu_shape_id = None
        gpu_ms = 0.0
        reason = ""
        viewport = self.viewport()
        target_width, target_height = backend.id_target_size
        target_x = viewport_pos.x() * target_width / max(1, viewport.width())
        target_y = viewport_pos.y() * target_height / max(1, viewport.height())
        try:
            viewport.makeCurrent()
            gpu_shape_id, gpu_ms, reason = backend.pick_device_pixel(target_x, target_y)
        except Exception as error:
            reason = str(error)
        finally:
            try:
                viewport.doneCurrent()
            except Exception:
                pass
        cpu_shape_id = cpu_shape.id if cpu_shape else ""
        gpu_id = gpu_shape_id or ""
        available = not reason
        comparison = PickComparison(
            cpu_shape_id, gpu_id, cpu_ms, gpu_ms,
            matched=available and cpu_shape_id == gpu_id,
            gpu_available=available, fallback_reason=reason)
        backend.record_pick_comparison(comparison)
        self.canvas.profiler.set_gauge("pick_cpu_ms", cpu_ms)
        self.canvas.profiler.set_gauge("pick_gpu_readback_ms", gpu_ms)
        self.canvas.profiler.set_gauge("pick_matched", comparison.matched)
        self.offscreen_experiment_changed.emit()
        if self.picking_mode == "gpu" and available:
            return next((shape for shape in self.canvas.shapes
                         if shape.id == gpu_shape_id), None)
        return cpu_shape

    def id_attachment_image(self):
        backend = self.render_item.backend
        viewport = self.viewport()
        if not isinstance(backend, OpenGLBackend) or not hasattr(viewport, "makeCurrent"):
            return None
        try:
            viewport.makeCurrent()
            return backend.id_attachment_image()
        finally:
            viewport.doneCurrent()

    def set_pipeline_debug_mode(self, mode: str) -> None:
        self.render_item.pipeline_mode = PipelineDebugMode(mode).value
        self.scene.update()

    def pipeline_snapshot(self):
        """Return a read-only trace of the currently active rendering backend."""
        selected = self.canvas.get_selected_shapes()
        selected_id = selected[0].id if len(selected) == 1 else None
        viewport = self.get_viewport_rect().intersected(
            QRectF(0, 0, self.canvas.width, self.canvas.height))
        bounds = (viewport.left(), viewport.top(), viewport.right(), viewport.bottom())
        device = self.viewport()
        return build_pipeline_snapshot(
            self.canvas, self.render_item.backend, self.viewportTransform(),
            (device.width(), device.height()), bounds, selected_id,
            self.render_item.pipeline_mode)

    def render_backend_status(self) -> str:
        backend = self.render_item.backend
        if isinstance(backend, OpenGLBackend):
            if backend.fallback_active:
                return f"OpenGL 回退到 QPainter：{backend.last_error}"
            if backend.program is None:
                return "OpenGL 后端正在等待首帧初始化"
            samples = backend.context.format().samples() if backend.context else 0
            antialiasing = f"MSAA {samples}x + coverage" if samples else "coverage AA"
            experiment = backend.experiment_state()
            offscreen = backend.offscreen_state()
            instancing = backend.instancing_state()
            gpu_text = backend.gpu_text_state()
            return (f"OpenGL 已激活 | GPU 顶点: {backend.last_gpu_vertices} "
                    f"| 批次: {backend.last_gpu_batches} | 上传: {backend.last_upload_kind.value} "
                    f"{backend.last_upload_bytes} B/{backend.last_upload_ranges} 段 "
                    f"(全量 {backend.full_upload_count}/局部 {backend.partial_upload_count}) "
                    f"| Arena: {backend.arena.allocation_count} slots "
                    f"碎片 {backend.arena.fragmentation_ratio:.1%} "
                    f"dirty {backend.arena.last_shapes_touched} shapes | {antialiasing} "
                    f"| Geometry: {geometry_backend_name()} "
                    f"| Shader: {experiment['shader_mode']} "
                    f"Blend: {experiment['blend_mode']} "
                    f"Clip: {experiment['effective_clip_mode']} "
                    f"| Pick: {offscreen['picking_mode']} "
                    f"ID-FBO: {'ready' if offscreen['target_valid'] else 'off'} "
                    f"| Instances: {instancing['count'] if instancing['enabled'] else 'off'} "
                    f"| GPU Text: {gpu_text['rendered_glyphs'] if gpu_text['enabled'] else 'off'}")
        if isinstance(backend, CommandQPainterBackend):
            return f"命令缓冲 QPainter | 指令: {backend.last_primitive_count}"
        return "传统 QPainter"

    def set_multi_select(self, enabled: bool) -> None:
        self.multi_select_mode = enabled
        if enabled:
            self.canvas.set_selection_mode(SelectionMode.MULTI)
        else:
            self.canvas.set_selection_mode(SelectionMode.SINGLE)

    def get_current_tool(self) -> str:
        for name, tool in self.tool_manager.tools.items():
            if tool == self.tool_manager.current_tool:
                return name
        return None

    def get_scene_pos(self, screen_pos: QPointF) -> QPointF:
        return self.mapToScene(screen_pos.toPoint())

    def get_viewport_rect(self) -> QRectF:
        return self.mapToScene(self.viewport().rect()).boundingRect()

    def center_on_point(self, point: QPointF) -> None:
        self.centerOn(point)


class SceneRenderItem(QGraphicsItem):
    """画布渲染项 — 绘制白色背景、网格、所有图形"""

    def __init__(self, canvas: Canvas):
        super().__init__()
        self.canvas = canvas
        self.backend = QPainterBackend()
        self.status_callback = None
        self.pipeline_mode = PipelineDebugMode.FINAL.value
        self.lighting_snapshot_provider = None

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.canvas.width, self.canvas.height)

    def set_backend(self, backend):
        self.backend.release()
        self.backend = backend
        self.canvas.invalidate_render(RenderDirtyFlag.ALL, full_sync=True)
        self.update()

    def paint(self, painter: QPainter, option, widget):
        profiler = self.canvas.profiler
        with profiler.measure("frame_total"):
            if self.backend.uses_render_delta:
                document = self.canvas.consume_render_delta()
                dirty_flags = RenderDirtyFlag(document.dirty_flags)
            else:
                document = self.canvas.create_render_snapshot() if self.backend.requires_snapshot else self.canvas
                dirty_flags = self.canvas.consume_render_dirty_flags()
            with profiler.measure("render_sync"):
                self.backend.sync_document(document, dirty_flags)
            lighting_snapshot = (self.lighting_snapshot_provider()
                                 if self.lighting_snapshot_provider else None)
            if hasattr(self.backend, "set_lighting_snapshot"):
                self.backend.set_lighting_snapshot(lighting_snapshot)
            with profiler.measure("backend_render"):
                self.backend.render(painter, option.exposedRect)
            if self.pipeline_mode != PipelineDebugMode.FINAL.value:
                with profiler.measure("pipeline_debug"):
                    viewport = option.exposedRect.intersected(self.boundingRect())
                    selected = self.canvas.get_selected_shapes()
                    selected_id = selected[0].id if len(selected) == 1 else None
                    device = painter.device()
                    snapshot = build_pipeline_snapshot(
                        self.canvas, self.backend, painter.combinedTransform(),
                        (device.width(), device.height()),
                        (viewport.left(), viewport.top(), viewport.right(), viewport.bottom()),
                        selected_id, self.pipeline_mode)
                    draw_pipeline_overlay(painter, snapshot, self.pipeline_mode)
            if self.lighting_snapshot_provider:
                with profiler.measure("visibility_polygon"):
                    draw_lighting_debug(painter, lighting_snapshot)
            if self.canvas.preview_shapes:
                with profiler.measure("preview_render"):
                    painter.save()
                    for shape in tuple(self.canvas.preview_shapes):
                        shape.paint(painter, pass_type=0)
                    painter.restore()
        try:
            self._record_render_gauges()
        except Exception as error:
            # Metrics are diagnostic only. Never let a Python exception cross
            # QGraphicsItem.paint's C++ virtual callback and abort the process.
            profiler.set_gauge("render_observability_error", str(error))
        if self.status_callback:
            try:
                self.status_callback()
            except Exception as error:
                profiler.set_gauge("render_status_error", str(error))

    def _record_render_gauges(self):
        profiler = self.canvas.profiler
        backend = self.backend
        profiler.set_gauge("render_backend", type(backend).__name__)
        profiler.set_gauge("shape_count", len(self.canvas.shapes))
        profiler.set_gauge("geometry_backend", geometry_backend_name())
        if hasattr(backend, "last_total_shapes"):
            profiler.set_gauge("visible_shapes", backend.last_visible_shapes)
        if hasattr(backend, "last_primitive_count"):
            profiler.set_gauge("visible_primitives", backend.last_primitive_count)
        if isinstance(backend, OpenGLBackend):
            profiler.set_gauge("gpu_vertices", backend.last_gpu_vertices)
            profiler.set_gauge("gpu_batches", backend.last_gpu_batches)
            profiler.set_gauge("gpu_allocations", backend.arena.allocation_count)
            profiler.set_gauge("gpu_fragmentation", backend.arena.fragmentation_ratio)
            profiler.set_gauge("dirty_shapes", backend.arena.last_shapes_touched)
            profiler.set_gauge("opengl_fallback", backend.fallback_active)
            experiment = backend.experiment_state()
            profiler.set_gauge("shader_mode", experiment["shader_mode"])
            profiler.set_gauge("blend_mode", experiment["blend_mode"])
            profiler.set_gauge("clip_mode", experiment["effective_clip_mode"])
            offscreen = backend.offscreen_state()
            profiler.set_gauge("picking_mode", offscreen["picking_mode"])
            profiler.set_gauge("id_target_valid", offscreen["target_valid"])
            instancing = backend.instancing_state()
            profiler.set_gauge("instance_count", instancing["count"])
            profiler.set_gauge("instance_bytes", instancing["instance_bytes"])
            profiler.set_gauge("instanced_draw_calls", instancing["draw_calls"])
            profiler.set_gauge("instance_upload_count", instancing["upload_count"])
            gpu_text = backend.gpu_text_state()
            profiler.set_gauge("glyph_count", gpu_text["unique_glyphs"])
            profiler.set_gauge("glyph_vertices", gpu_text["vertices"])
            profiler.set_gauge("glyph_vbo_bytes", gpu_text["vbo_bytes"])
            profiler.set_gauge("gpu_text_draw_calls", gpu_text["draw_calls"])
            profiler.set_gauge("glyph_upload_count", gpu_text["upload_count"])
            lighting_gpu = backend.lighting_state()
            profiler.set_gauge("lighting_fan_vertices", lighting_gpu["fan_vertices"])
            profiler.set_gauge("lighting_fbo_bytes", lighting_gpu["fbo_bytes"])
            profiler.set_gauge("lighting_draw_calls", lighting_gpu["draw_calls"])
            profiler.set_gauge("lighting_upload_count", lighting_gpu["upload_count"])
            profiler.set_gauge("lighting_count", lighting_gpu["light_count"])
        if self.lighting_snapshot_provider:
            lighting = self.lighting_snapshot_provider()
            if lighting:
                profiler.set_gauge("visibility_segments", len(lighting.segments))
                profiler.set_gauge("visibility_rays", sum(
                    len(item.result.rays) for item in lighting.light_visibilities))
                profiler.set_gauge("visibility_tests",
                                   sum(item.result.intersection_tests
                                       for item in lighting.light_visibilities))
                profiler.set_gauge("visibility_backend", lighting.result.backend)
