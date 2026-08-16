import os
import sys
import unittest


SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtCore import QRectF
from PyQt5.QtGui import QColor, QImage, QPainter

from core.canvas import Canvas
from core.rendering import CommandQPainterBackend, QPainterBackend
from core.opengl_backend import OpenGLBackend


def render_backend(backend, width, height):
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(QColor("black"))
    painter = QPainter(image)
    backend.render(painter, QRectF(0, 0, width, height))
    painter.end()
    return image


class RenderBackendTests(unittest.TestCase):
    def setUp(self):
        self.canvas = Canvas(160, 120)
        self.canvas.show_grid = False
        self.canvas.show_engine_debug = False
        self.shape = self.canvas.create_rectangle(20, 20, 40, 30)
        self.shape.style.brush_color = "#E53935"
        self.canvas.add_shape(self.shape)

    def test_legacy_backend_still_renders(self):
        backend = QPainterBackend()
        backend.sync_document(self.canvas, self.canvas.consume_render_dirty_flags())

        image = render_backend(backend, 160, 120)

        self.assertEqual(image.pixelColor(30, 30), QColor("#E53935"))

    def test_command_backend_renders_and_applies_incremental_move(self):
        backend = CommandQPainterBackend(self.canvas)
        backend.sync_document(self.canvas.consume_render_delta(force_full=True), 0)
        image = render_backend(backend, 160, 120)
        self.assertEqual(image.pixelColor(30, 30), QColor("#E53935"))
        initial_compiles = backend.cache.compiler.compile_count

        self.canvas.move_shapes([self.shape], 50, 0)
        backend.sync_document(self.canvas.consume_render_delta(), 0)
        moved_image = render_backend(backend, 160, 120)

        self.assertEqual(backend.cache.compiler.compile_count - initial_compiles, 1)
        self.assertEqual(moved_image.pixelColor(30, 30), QColor("white"))
        self.assertEqual(moved_image.pixelColor(80, 30), QColor("#E53935"))

    def test_opengl_backend_falls_back_without_a_gl_context(self):
        backend = OpenGLBackend(self.canvas)
        backend.sync_document(self.canvas.consume_render_delta(force_full=True), 0)

        image = render_backend(backend, 160, 120)

        self.assertTrue(backend.fallback_active)
        self.assertIn("OpenGL context", backend.last_error)
        self.assertEqual(image.pixelColor(30, 30), QColor("#E53935"))


if __name__ == "__main__":
    unittest.main()
