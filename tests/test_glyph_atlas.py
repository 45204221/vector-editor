import os
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtWidgets import QApplication

from core.canvas import Canvas
from core.glyph_atlas import (ATLAS_SIZE, MAX_GLYPHS, TEXT_VERTEX_STRIDE,
                              GpuTextConfig, build_glyph_atlas,
                              build_text_frame)
from core.gpu_buffers import GpuTextCommand
from ui.main_window import MainWindow


APP = QApplication.instance() or QApplication([])


def command(text="GPU中文", width=240, transform=(1, 0, 0, 1, 0, 0)):
    return GpuTextCommand(
        "text-1", (0, 0, width, 80),
        ((0, 0), (width, 0), (width, 80), (0, 80)), transform,
        (0.1, 0.2, 0.3, 1.0), text, 18.0)


class GlyphAtlasTests(unittest.TestCase):
    def test_atlas_contains_ascii_and_chinese_alpha(self):
        image, cells = build_glyph_atlas("GPU中文")
        self.assertEqual((image.width(), image.height()), ATLAS_SIZE)
        self.assertEqual(set(cells), set("GPU中文"))
        self.assertTrue(any(image.pixelColor(x, y).alpha() > 0
                            for y in range(0, 128, 4)
                            for x in range(0, 320, 4)))

    def test_frame_has_deterministic_interleaved_vertices(self):
        first = build_text_frame((command("GPU"),))
        second = build_text_frame((command("GPU"),))
        self.assertEqual(first.key, second.key)
        self.assertEqual(first.payload, second.payload)
        self.assertEqual(first.glyph_count, 3)
        self.assertEqual(first.vertex_count, 18)
        self.assertEqual(len(first.payload), 18 * TEXT_VERTEX_STRIDE)
        self.assertEqual(first.ranges, ((0, 18),))

    def test_transform_and_wrap_are_applied_to_scene_vertices(self):
        base = build_text_frame((command("AB", width=12),))
        moved = build_text_frame((command("AB", width=12,
                                          transform=(1, 0, 0, 1, 25, 30)),))
        base_positions = list(zip(base.vertices[0::8], base.vertices[1::8]))
        moved_positions = list(zip(moved.vertices[0::8], moved.vertices[1::8]))
        self.assertTrue(all(abs(mx - bx - 25) < 1e-5 and abs(my - by - 30) < 1e-5
                            for (bx, by), (mx, my) in zip(base_positions, moved_positions)))
        self.assertGreater(base_positions[6][1], base_positions[0][1])

    def test_capacity_overflow_falls_back_whole_command(self):
        text = "".join(chr(0x4E00 + index) for index in range(MAX_GLYPHS + 1))
        frame = build_text_frame((command(text, width=100000),))
        self.assertEqual(len(frame.cells), MAX_GLYPHS)
        self.assertEqual(frame.fallback_indexes, (0,))
        self.assertEqual(frame.vertex_count, 0)

    def test_runtime_switch_is_history_neutral_and_safe_without_context(self):
        window = MainWindow()
        view = window.graphics_view
        before = (window.canvas.history_manager.current_index,
                  window.canvas.render_revision)
        view.set_gpu_text_experiment(True)
        self.assertEqual((window.canvas.history_manager.current_index,
                          window.canvas.render_revision), before)
        state = view.gpu_text_experiment_state()
        self.assertTrue(state["enabled"])
        self.assertFalse(state["resources_valid"])
        self.assertEqual(state["atlas_bytes"], 4 * 1024 * 1024)
        self.assertTrue(window.instancing_panel.gpu_text_check.isChecked())
        window.close()

    def test_config_is_immutable(self):
        config = GpuTextConfig()
        self.assertFalse(config.enabled)
        self.assertTrue(config.show_demo)
        self.assertTrue(config.changed(enabled=True).enabled)

    def test_runtime_demo_is_a_non_document_text_command(self):
        from core.opengl_backend import OpenGLBackend
        backend = OpenGLBackend(Canvas(1000, 600))
        demo = backend._gpu_text_demo_command(800, 600)
        frame = build_text_frame((demo,))
        self.assertEqual(demo.shape_id, "__runtime_gpu_text_demo__")
        self.assertIn("GPU Glyph Atlas", demo.text)
        self.assertGreater(frame.glyph_count, 20)
        self.assertGreater(frame.vertex_count, 0)


if __name__ == "__main__":
    unittest.main()
