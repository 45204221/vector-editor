import os
import struct
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtWidgets import QApplication

from core.canvas import Canvas
from core.instancing_experiment import (ATLAS_SIZE, INSTANCE_STRIDE_BYTES,
                                        MAX_INSTANCES, InstancingConfig,
                                        build_instance_data, build_sprite_atlas)
from core.opengl_backend import (SPRITE_FRAGMENT_SHADER, SPRITE_VERTEX_SHADER,
                                 OpenGLBackend)
from ui.main_window import MainWindow
from widgets.graphics_view import GraphicsView


APP = QApplication.instance() or QApplication([])


class InstancingDataTests(unittest.TestCase):
    def test_config_bounds_and_deterministic_buffer(self):
        config = InstancingConfig(count=12, sprite_mode="mixed", seed=42)
        first = build_instance_data(config, 800, 600)
        second = build_instance_data(config, 800, 600)
        self.assertEqual(first, second)
        self.assertEqual(len(first.payload), 12 * INSTANCE_STRIDE_BYTES)
        values = struct.unpack("<{}f".format(12 * 14), first.payload)
        uv_rects = [values[index * 14 + 10:index * 14 + 14] for index in range(3)]
        self.assertAlmostEqual(uv_rects[0][0], 0.0)
        self.assertAlmostEqual(uv_rects[1][0], 1.0 / 3.0, places=6)
        self.assertAlmostEqual(uv_rects[2][0], 2.0 / 3.0, places=6)
        with self.assertRaises(ValueError):
            InstancingConfig(count=MAX_INSTANCES + 1)
        with self.assertRaises(ValueError):
            InstancingConfig(sprite_mode="unknown")

    def test_atlas_and_shader_contract(self):
        atlas = build_sprite_atlas()
        self.assertEqual((atlas.width(), atlas.height()), ATLAS_SIZE)
        for x in (32, 96, 160):
            self.assertGreater(atlas.pixelColor(x, 32).alpha(), 0)
        self.assertIn("attribute vec2 i_base", SPRITE_VERTEX_SHADER)
        self.assertIn("attribute vec4 i_uv_rect", SPRITE_VERTEX_SHADER)
        self.assertIn("uniform sampler2D u_atlas", SPRITE_FRAGMENT_SHADER)


class InstancingRuntimeTests(unittest.TestCase):
    def test_runtime_config_is_history_neutral_on_non_gl_backend(self):
        canvas = Canvas(200, 100)
        view = GraphicsView(canvas)
        revision = canvas.render_revision
        history = canvas.history_manager.current_index

        view.set_instancing_experiment(True, 1000, "star", True, 9)

        state = view.instancing_experiment_state()
        self.assertTrue(state["enabled"])
        self.assertEqual(state["count"], 1000)
        self.assertEqual(state["sprite_mode"], "star")
        self.assertFalse(view.sprite_timer.isActive())
        self.assertEqual(canvas.render_revision, revision)
        self.assertEqual(canvas.history_manager.current_index, history)
        view.close()

    def test_backend_state_is_safe_without_context(self):
        backend = OpenGLBackend(Canvas(200, 100))
        backend.set_instancing_config(InstancingConfig(True, 10, "circle", False, 3))
        state = backend.instancing_state()
        self.assertTrue(state["enabled"])
        self.assertFalse(state["resources_valid"])
        self.assertEqual(state["draw_calls"], 0)

    def test_engine_lab_page_controls_are_history_neutral(self):
        window = MainWindow()
        revision = window.canvas.render_revision
        history = window.canvas.history_manager.current_index
        window.show_instancing_panel()
        APP.processEvents()
        panel = window.instancing_panel
        panel.count_spin.setValue(750)
        panel.enabled_check.setChecked(True)
        APP.processEvents()
        self.assertEqual(window.engine_lab_window.pages.currentIndex(), 2)
        self.assertEqual(window.graphics_view.instancing_config.count, 750)
        self.assertEqual(window.canvas.render_revision, revision)
        self.assertEqual(window.canvas.history_manager.current_index, history)
        window.close()


if __name__ == "__main__":
    unittest.main()
