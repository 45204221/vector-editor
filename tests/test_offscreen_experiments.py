import os
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtCore import QPoint, QPointF
from PyQt5.QtWidgets import QApplication

from core.canvas import Canvas
from core.offscreen_experiments import (MAX_PICK_ID, PickComparison,
                                        decode_pick_id, encode_pick_id,
                                        estimated_target_bytes, offscreen_dimensions,
                                        validate_attachment_view,
                                        validate_picking_mode, validate_postprocess)
from core.opengl_backend import (FRAGMENT_SHADER, POST_FRAGMENT_SHADER,
                                 POST_VERTEX_SHADER, OpenGLBackend)
from ui.main_window import MainWindow
from widgets.graphics_view import GraphicsView


APP = QApplication.instance() or QApplication([])


class PickEncodingTests(unittest.TestCase):
    def test_24_bit_round_trip_and_bounds(self):
        for value in (0, 1, 0x123456, MAX_PICK_ID):
            color = encode_pick_id(value)
            self.assertEqual(decode_pick_id(*color[:3]), value)
            self.assertEqual(color[3], 255)
        for invalid in (-1, MAX_PICK_ID + 1):
            with self.assertRaises(ValueError):
                encode_pick_id(invalid)

    def test_mode_validation_and_shader_contract(self):
        for mode in ("cpu", "compare", "gpu"):
            self.assertEqual(validate_picking_mode(mode), mode)
        with self.assertRaises(ValueError):
            validate_picking_mode("magic")
        self.assertIn("uniform int u_pick_mode", FRAGMENT_SHADER)
        self.assertIn("uniform vec4 u_pick_color", FRAGMENT_SHADER)

    def test_postprocess_contract_dimensions_and_resource_limit(self):
        for mode in ("none", "grayscale", "invert", "edge"):
            self.assertEqual(validate_postprocess(mode), mode)
        for view in ("color", "postprocess", "id"):
            self.assertEqual(validate_attachment_view(view), view)
        self.assertEqual(offscreen_dimensions(320, 200, 2), (640, 400))
        self.assertEqual(estimated_target_bytes(640, 400), 640 * 400 * 12)
        with self.assertRaises(ValueError):
            offscreen_dimensions(5000, 4000, 1)
        self.assertIn("attribute vec2 a_uv", POST_VERTEX_SHADER)
        self.assertIn("uniform sampler2D u_texture", POST_FRAGMENT_SHADER)
        self.assertIn("u_texel_size", POST_FRAGMENT_SHADER)


class OffscreenViewTests(unittest.TestCase):
    def test_mode_is_history_neutral_and_non_gl_falls_back_to_cpu(self):
        canvas = Canvas(200, 100)
        shape = canvas.create_rectangle(20, 20, 50, 40)
        canvas.add_shape(shape)
        view = GraphicsView(canvas)
        revision = canvas.render_revision
        history = canvas.history_manager.current_index

        view.set_picking_mode("compare")
        picked = view.hit_test_for_selection(QPointF(30, 30), QPoint(30, 30))

        self.assertIs(picked, shape)
        self.assertEqual(view.offscreen_experiment_state()["picking_mode"], "compare")
        self.assertFalse(view.offscreen_experiment_state()["target_valid"])
        self.assertEqual(canvas.render_revision, revision)
        self.assertEqual(canvas.history_manager.current_index, history)
        view.close()

    def test_backend_state_and_comparison_are_pure_runtime_data(self):
        backend = OpenGLBackend(Canvas(200, 100))
        backend.set_picking_mode("gpu")
        comparison = PickComparison("cpu-id", "gpu-id", 0.1, 0.2, False, True)
        backend.record_pick_comparison(comparison)
        state = backend.offscreen_state()

        self.assertEqual(state["picking_mode"], "gpu")
        self.assertEqual(state["cpu_shape_id"], "cpu-id")
        self.assertEqual(state["gpu_shape_id"], "gpu-id")
        self.assertFalse(state["matched"])

    def test_panel_mode_control_does_not_modify_document(self):
        window = MainWindow()
        revision = window.canvas.render_revision
        history = window.canvas.history_manager.current_index
        index = window.pipeline_panel.picking_combo.findData("compare")

        window.pipeline_panel.picking_combo.setCurrentIndex(index)
        APP.processEvents()

        self.assertEqual(window.graphics_view.picking_mode, "compare")
        self.assertEqual(window.canvas.render_revision, revision)
        self.assertEqual(window.canvas.history_manager.current_index, history)
        window.close()

    def test_preview_configuration_is_history_neutral(self):
        canvas = Canvas(200, 100)
        view = GraphicsView(canvas)
        revision = canvas.render_revision
        history = canvas.history_manager.current_index

        view.set_offscreen_preview_config("edge", "color", 2)

        self.assertEqual(view.postprocess_mode, "edge")
        self.assertEqual(view.attachment_view, "color")
        self.assertEqual(view.offscreen_scale, 2)
        self.assertEqual(canvas.render_revision, revision)
        self.assertEqual(canvas.history_manager.current_index, history)
        view.close()

    def test_manual_render_without_gl_context_returns_explained_failure(self):
        canvas = Canvas(200, 100)
        backend = OpenGLBackend(canvas)

        image = backend.render_offscreen_attachment("invert", 1, "postprocess")

        self.assertIsNone(image)
        self.assertIn("OpenGL context", backend.last_offscreen_error)


if __name__ == "__main__":
    unittest.main()
