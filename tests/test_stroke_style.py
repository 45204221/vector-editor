import os
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from core.canvas import Canvas
from core.geometry import GeometryCache
from core.gpu_buffers import VERTEX_STRIDE_FLOATS, encode_gpu_primitive
from core.shape import Shape
from PyQt5.QtWidgets import QApplication
from ui.properties import PropertiesPanel


APP = QApplication.instance() or QApplication([])


class StrokeStyleTests(unittest.TestCase):
    def test_old_document_uses_backward_compatible_defaults(self):
        canvas = Canvas(500, 400)
        data = canvas.create_rectangle(20, 20, 40, 30).to_dict()
        data["style"].pop("line_join")
        data["style"].pop("line_cap")

        restored = Shape.from_dict(data)

        self.assertEqual(restored.style.line_join, "miter")
        self.assertEqual(restored.style.line_cap, "butt")

    def test_join_and_cap_survive_history_undo_redo(self):
        canvas = Canvas(500, 400)
        shape = canvas.create_rectangle(20, 20, 40, 30)
        canvas.add_shape(shape)
        shape.style.line_join = "round"
        shape.style.line_cap = "square"
        canvas.update_world_state(emit=False, changed_shapes=[shape])
        canvas.record_history("描边样式")

        self.assertTrue(canvas.undo())
        self.assertEqual(canvas.shapes[0].style.line_join, "miter")
        self.assertEqual(canvas.shapes[0].style.line_cap, "butt")
        self.assertTrue(canvas.redo())
        self.assertEqual(canvas.shapes[0].style.line_join, "round")
        self.assertEqual(canvas.shapes[0].style.line_cap, "square")

    def test_scaled_line_expands_width_in_local_space(self):
        canvas = Canvas(500, 400)
        canvas.snap_to_grid = False
        line = canvas.create_line(10, 20, 110, 20)
        line.style.pen_width = 4
        line.transform.scale(2, 2)
        canvas.add_shape(line)
        cache = GeometryCache()
        cache.sync_snapshot(canvas.create_render_snapshot())
        primitive = cache.primitives_for_shape(line.id)[0]

        topology, _, encoded = encode_gpu_primitive(primitive)
        points = [(encoded[index], encoded[index + 1], encoded[index + 5])
                  for index in range(0, len(encoded), VERTEX_STRIDE_FLOATS)]
        ys = [point[1] for point in points]
        opaque_ys = [point[1] for point in points if point[2] == 1.0]

        self.assertEqual(topology.value, "triangles")
        self.assertAlmostEqual(min(opaque_ys), 36.0)
        self.assertAlmostEqual(max(opaque_ys), 44.0)
        self.assertAlmostEqual(min(ys), 34.0)
        self.assertAlmostEqual(max(ys), 46.0)

    def test_properties_panel_updates_join_and_cap_as_one_history_change(self):
        canvas = Canvas(500, 400)
        shape = canvas.create_line(20, 20, 100, 20)
        canvas.add_shape(shape)
        panel = PropertiesPanel(canvas)
        canvas.select_shape(shape)

        panel.line_join_combo.setCurrentIndex(2)
        panel.line_cap_combo.setCurrentIndex(1)
        canvas.commit_history_transaction()

        self.assertEqual(shape.style.line_join, "round")
        self.assertEqual(shape.style.line_cap, "square")
        self.assertTrue(canvas.undo())
        self.assertEqual(canvas.shapes[0].style.line_join, "miter")
        self.assertEqual(canvas.shapes[0].style.line_cap, "butt")


if __name__ == "__main__":
    unittest.main()
