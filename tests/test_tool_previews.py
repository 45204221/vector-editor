import os
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QImage, QPainter
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from core.shape import ConnectionShape, ShapeType
from ui.main_window import MainWindow


class ToolPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.window.resize(1000, 700)
        self.window.show()
        self.view = self.window.graphics_view
        self.canvas = self.window.canvas
        self.canvas.show_grid = False
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def _screen(self, x, y):
        return self.view.mapFromScene(QPointF(x, y))

    def _click(self, x, y):
        QTest.mouseClick(self.view.viewport(), Qt.LeftButton, pos=self._screen(x, y))

    def _render_scene(self):
        image = QImage(500, 400, QImage.Format_ARGB32)
        image.fill(Qt.white)
        painter = QPainter(image)
        self.view.scene.render(painter, QRectF(0, 0, 500, 400), QRectF(0, 0, 500, 400))
        painter.end()
        return image

    def test_polygon_preview_is_overlay_not_document_and_is_visible(self):
        self.view.set_render_backend("command")
        self.view.set_tool("polygon")
        initial_history = self.canvas.history_manager.current_index
        self._click(100, 100)
        self._click(200, 100)
        self.app.processEvents()

        self.assertEqual(len(self.canvas.preview_shapes), 1)
        self.assertEqual(self.canvas.shapes, [])
        self.assertEqual(self.canvas.create_render_snapshot().shapes, ())
        self.assertEqual(self.canvas.history_manager.current_index, initial_history)
        self.assertIsNone(self.canvas.hit_test(QPointF(150, 100)))
        self.assertTrue(self.view.viewport().hasMouseTracking())
        image = self._render_scene()
        pixel = image.pixelColor(150, 100)
        self.assertGreater(pixel.blue(), pixel.red())

    def test_polygon_and_polyline_finish_once_and_clear_preview(self):
        for tool_name, expected_type, points in (
                ("polygon", ShapeType.POLYGON,
                 ((100, 100), (200, 100), (150, 200))),
                ("polyline", ShapeType.POLYLINE,
                 ((300, 100), (400, 150), (300, 200)))):
            self.view.set_tool(tool_name)
            for point in points:
                self._click(*point)
            QTest.mouseDClick(
                self.view.viewport(), Qt.LeftButton, pos=self._screen(*points[-1]))
            self.app.processEvents()
            self.assertEqual(self.canvas.preview_shapes, [])
            self.assertEqual(self.canvas.shapes[-1].shape_type, expected_type)

        self.assertEqual(len(self.canvas.shapes), 2)

    def test_connection_preview_is_transient_and_final_connection_is_undoable(self):
        first = self.canvas.create_rectangle(100, 100, 80, 60)
        second = self.canvas.create_rectangle(400, 200, 80, 60)
        self.canvas.add_shape(first)
        self.canvas.add_shape(second)
        self.view.set_tool("connection")
        source = self._screen(*self._point_tuple(first.bounding_rect().center()))
        target = self._screen(*self._point_tuple(second.bounding_rect().center()))

        QTest.mousePress(self.view.viewport(), Qt.LeftButton, pos=source)
        QTest.mouseMove(self.view.viewport(), target)
        self.app.processEvents()
        self.assertEqual(len(self.canvas.preview_shapes), 1)
        self.assertEqual(len(self.canvas.shapes), 2)

        QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, pos=target)
        self.app.processEvents()
        self.assertEqual(self.canvas.preview_shapes, [])
        self.assertEqual(len(self.canvas.shapes), 3)
        self.assertIsInstance(self.canvas.shapes[-1], ConnectionShape)
        self.assertTrue(self.canvas.undo())
        self.assertEqual(len(self.canvas.shapes), 2)

    def test_switching_tools_clears_unfinished_preview(self):
        self.view.set_tool("polyline")
        self._click(100, 100)
        self._click(200, 150)
        self.assertEqual(len(self.canvas.preview_shapes), 1)

        self.view.set_tool("select")

        self.assertEqual(self.canvas.preview_shapes, [])

    def test_escape_cancels_preview_without_changing_active_tool(self):
        self.view.set_tool("polygon")
        self._click(100, 100)
        self._click(200, 100)
        self.assertEqual(len(self.canvas.preview_shapes), 1)

        QTest.keyClick(self.view, Qt.Key_Escape)

        self.assertEqual(self.canvas.preview_shapes, [])
        self.assertEqual(self.view.get_current_tool(), "polygon")

    @staticmethod
    def _point_tuple(point):
        return point.x(), point.y()


if __name__ == "__main__":
    unittest.main()
