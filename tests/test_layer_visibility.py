import os
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from core.canvas import Canvas
from ui.layer_panel import LayerPanel


APP = QApplication.instance() or QApplication([])


class LayerVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.canvas = Canvas(300, 200)
        self.shape = self.canvas.create_rectangle(20, 20, 40, 30)
        self.canvas.add_shape(self.shape)
        self.panel = LayerPanel(self.canvas)
        self.canvas.consume_render_delta(force_full=True)

    def test_explicit_button_hides_and_restores_current_layer(self):
        self.assertEqual(self.panel.visibility_button.text(), "隐藏图层")

        self.panel.visibility_button.click()

        self.assertFalse(self.canvas.layer_manager.get("content").visible)
        self.assertEqual(self.canvas.sorted_shapes(), [])
        self.assertEqual(self.panel.visibility_button.text(), "显示图层")
        hidden_delta = self.canvas.consume_render_delta()
        self.assertFalse(hidden_delta.full_sync)
        self.assertEqual(hidden_delta.ordered_shape_ids, ())

        self.panel.visibility_button.click()

        self.assertTrue(self.canvas.layer_manager.get("content").visible)
        self.assertEqual(self.canvas.sorted_shapes(), [self.shape])

    def test_checkbox_visibility_change_is_undoable(self):
        item = self.panel.list.currentItem()
        item.setCheckState(Qt.Unchecked)
        self.assertFalse(self.canvas.layer_manager.get("content").visible)

        self.canvas.undo()

        self.assertTrue(self.canvas.layer_manager.get("content").visible)
        self.assertEqual(self.panel.list.currentItem().checkState(), Qt.Checked)


if __name__ == "__main__":
    unittest.main()
