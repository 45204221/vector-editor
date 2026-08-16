import os
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QAction, QToolBar

from core.canvas import Canvas
from ui.main_window import MainWindow


class CanvasHistoryResultTests(unittest.TestCase):
    def test_undo_and_redo_report_whether_state_changed(self):
        canvas = Canvas(500, 400)
        self.assertFalse(canvas.undo())
        self.assertFalse(canvas.redo())

        shape = canvas.create_rectangle(20, 20, 40, 40)
        canvas.add_shape(shape)
        self.assertTrue(canvas.undo())
        self.assertTrue(canvas.redo())
        self.assertFalse(canvas.redo())


class MainWindowHistoryActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def _build_moved_shape(self):
        canvas = self.window.canvas
        shape = canvas.create_rectangle(20, 20, 40, 40)
        canvas.add_shape(shape)
        canvas.move_shapes([shape], 50, 0)
        self.app.processEvents()
        return canvas

    def test_menu_and_toolbar_share_one_undo_and_redo_action(self):
        undo_actions = [action for action in self.window.findChildren(QAction)
                        if action.text().startswith("撤销")]
        redo_actions = [action for action in self.window.findChildren(QAction)
                        if action.text().startswith("重做")]

        self.assertEqual(undo_actions, [self.window.undo_action])
        self.assertEqual(redo_actions, [self.window.redo_action])
        self.assertFalse(self.window.undo_action.isEnabled())
        self.assertFalse(self.window.redo_action.isEnabled())

    def test_toolbar_click_redoes_previous_move(self):
        canvas = self._build_moved_shape()
        self.window.undo_action.trigger()
        self.app.processEvents()
        self.assertEqual(canvas.shapes[0].bounding_rect().x(), 20.0)
        self.assertTrue(self.window.redo_action.isEnabled())

        edit_toolbar = next(toolbar for toolbar in self.window.findChildren(QToolBar)
                            if toolbar.windowTitle() == "编辑")
        redo_button = edit_toolbar.widgetForAction(self.window.redo_action)
        QTest.mouseClick(redo_button, Qt.LeftButton)
        self.app.processEvents()

        self.assertEqual(canvas.shapes[0].bounding_rect().x(), 70.0)
        self.assertFalse(self.window.redo_action.isEnabled())

    def test_ctrl_z_and_ctrl_y_follow_history(self):
        canvas = self._build_moved_shape()

        QTest.keyClick(self.window, Qt.Key_Z, Qt.ControlModifier)
        self.app.processEvents()
        self.assertEqual(canvas.shapes[0].bounding_rect().x(), 20.0)

        QTest.keyClick(self.window, Qt.Key_Y, Qt.ControlModifier)
        self.app.processEvents()
        self.assertEqual(canvas.shapes[0].bounding_rect().x(), 70.0)


if __name__ == "__main__":
    unittest.main()
