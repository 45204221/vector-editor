import os
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtGui import QTransform
from PyQt5.QtWidgets import QApplication

from core.canvas import Canvas
from core.opengl_backend import FRAGMENT_SHADER, VERTEX_SHADER, OpenGLBackend
from core.pipeline_debug import build_pipeline_snapshot
from core.raster_experiments import RasterExperimentConfig
from ui.main_window import MainWindow
from widgets.graphics_view import GraphicsView


APP = QApplication.instance() or QApplication([])


class RasterExperimentConfigTests(unittest.TestCase):
    def test_defaults_changes_and_validation(self):
        defaults = RasterExperimentConfig()
        self.assertEqual(defaults.as_dict(), {
            "shader_mode": "vertex_color",
            "blend_mode": "alpha",
            "clip_mode": "none",
        })
        changed = defaults.changed("time_pulse", "additive", "stencil")
        self.assertEqual(changed.shader_mode, "time_pulse")
        self.assertEqual(changed.blend_mode, "additive")
        self.assertEqual(changed.clip_mode, "stencil")
        with self.assertRaises(ValueError):
            RasterExperimentConfig(shader_mode="unknown")

    def test_shader_sources_expose_runtime_inputs(self):
        self.assertIn("v_screen_uv", VERTEX_SHADER)
        self.assertIn("uniform int u_shader_mode", FRAGMENT_SHADER)
        self.assertIn("uniform float u_time", FRAGMENT_SHADER)
        self.assertIn("v_color.a", FRAGMENT_SHADER)

    def test_pipeline_snapshot_reports_requested_experiment(self):
        canvas = Canvas(200, 100)
        canvas.add_shape(canvas.create_rectangle(20, 20, 50, 40))
        config = RasterExperimentConfig("coverage", "additive", "stencil")
        backend = OpenGLBackend(canvas, config)
        backend.sync_document(canvas.consume_render_delta(force_full=True), 0)
        snapshot = build_pipeline_snapshot(
            canvas, backend, QTransform(), (200, 100), (0, 0, 200, 100))
        state = dict(snapshot.state)

        self.assertEqual(state["u_shader_mode"], "coverage")
        self.assertEqual(state["Blend"], "additive")
        self.assertEqual(state["Clip 请求/实际"], "stencil / none")


class RasterExperimentViewTests(unittest.TestCase):
    def test_runtime_changes_are_document_and_history_neutral(self):
        canvas = Canvas(200, 100)
        view = GraphicsView(canvas)
        revision = canvas.render_revision
        history_index = canvas.history_manager.current_index
        document = canvas._capture_document_state()

        view.set_raster_experiment("time_pulse", "additive", "stencil")

        self.assertEqual(view.raster_experiment.shader_mode, "time_pulse")
        self.assertFalse(view.shader_timer.isActive())  # command/QPainter backend
        self.assertEqual(canvas.render_revision, revision)
        self.assertEqual(canvas.history_manager.current_index, history_index)
        self.assertEqual(canvas._capture_document_state(), document)
        view.close()

    def test_config_is_forwarded_to_rebuilt_opengl_backend(self):
        canvas = Canvas(200, 100)
        view = GraphicsView(canvas)
        view.set_raster_experiment("coverage", "opaque", "scissor")
        backend = OpenGLBackend(canvas, view.raster_experiment)
        view.render_item.set_backend(backend)

        self.assertEqual(backend.experiment_state()["shader_mode"], "coverage")
        self.assertEqual(backend.experiment_state()["blend_mode"], "opaque")
        self.assertEqual(backend.experiment_state()["clip_mode"], "scissor")
        view.close()

    def test_panel_controls_do_not_modify_history(self):
        window = MainWindow()
        history_index = window.canvas.history_manager.current_index
        revision = window.canvas.render_revision
        shader_index = window.pipeline_panel.shader_combo.findData("screen_gradient")
        blend_index = window.pipeline_panel.blend_combo.findData("additive")
        clip_index = window.pipeline_panel.clip_combo.findData("stencil")

        window.pipeline_panel.shader_combo.setCurrentIndex(shader_index)
        window.pipeline_panel.blend_combo.setCurrentIndex(blend_index)
        window.pipeline_panel.clip_combo.setCurrentIndex(clip_index)
        APP.processEvents()

        self.assertEqual(window.graphics_view.raster_experiment.shader_mode,
                         "screen_gradient")
        self.assertEqual(window.canvas.history_manager.current_index, history_index)
        self.assertEqual(window.canvas.render_revision, revision)
        window.close()


if __name__ == "__main__":
    unittest.main()
