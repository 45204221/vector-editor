import os
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QSignalSpy
from PyQt5.QtWidgets import QApplication

from core.canvas import Canvas
from core.geometry import GeometryCache
from core.gpu_arena import GpuArena
from core.physics import SpringConstraint
from ui.layer_panel import LayerPanel
from ui.main_window import MainWindow


APP = QApplication.instance() or QApplication([])


class CopyIdentityRegressionTests(unittest.TestCase):
    def test_canvas_copy_gets_fresh_id_and_distinct_gpu_allocations(self):
        canvas = Canvas(500, 300)
        original = canvas.create_rectangle(20, 20, 80, 50)
        canvas.add_shape(original)

        first_copy = canvas.copy_shapes([original])[0]
        second_copy = canvas.copy_shapes([original])[0]
        canvas.paste_shapes([first_copy, second_copy])

        ids = [shape.id for shape in canvas.shapes]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(first_copy.selected)
        cache = GeometryCache()
        cache.sync_snapshot(canvas.create_render_snapshot())
        arena = GpuArena()
        arena.rebuild(cache)
        self.assertEqual(cache.shape_count, 3)
        self.assertEqual({key[0] for key in arena.allocations}, set(ids))
        self.assertEqual(arena.allocation_count, 6)

    def test_main_window_repeated_paste_never_reuses_clipboard_id(self):
        window = MainWindow()
        original = window.canvas.create_rectangle(20, 20, 80, 50)
        window.canvas.add_shape(original)
        window.canvas.select_shape(original)

        window.copy()
        window.paste()
        window.paste()

        ids = [shape.id for shape in window.canvas.shapes]
        self.assertEqual(len(ids), 3)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(window.canvas.get_selected_shapes(), [original])
        window.close()

    def test_add_shape_repairs_external_duplicate_identity(self):
        canvas = Canvas(500, 300)
        original = canvas.create_rectangle(20, 20, 80, 50)
        duplicate = canvas.create_rectangle(120, 20, 80, 50)
        duplicate.id = original.id
        canvas.add_shape(original)
        canvas.add_shape(duplicate)

        self.assertNotEqual(original.id, duplicate.id)


class PhysicsLayerPanelRegressionTests(unittest.TestCase):
    def test_physics_frames_do_not_rebuild_or_reset_layer_list(self):
        canvas = Canvas(500, 300)
        simulation_layer = canvas.layer_manager.add("模拟层")
        canvas.layers_changed.emit()
        first = canvas.create_rectangle(40, 40, 50, 40)
        second = canvas.create_rectangle(180, 40, 50, 40)
        canvas.add_shape(first)
        canvas.add_shape(second)
        first.layer_id = simulation_layer.id
        second.layer_id = simulation_layer.id
        first.rigid_body.enabled = second.rigid_body.enabled = True
        first.rigid_body.velocity_x = 30.0
        second.rigid_body.velocity_x = -20.0
        canvas.physics_world.springs.append(
            SpringConstraint(first.id, second.id, rest_length=120.0))

        panel = LayerPanel(canvas)
        target = next(panel.list.item(index) for index in range(panel.list.count())
                      if panel.list.item(index).data(Qt.UserRole) == simulation_layer.id)
        panel.list.setCurrentItem(target)
        self.assertEqual(canvas.layer_manager.active_layer_id, simulation_layer.id)
        rows_removed = QSignalSpy(panel.list.model().rowsRemoved)

        canvas.physics_world.running = True
        for _ in range(12):
            canvas.physics_step()
            APP.processEvents()

        self.assertEqual(len(rows_removed), 0)
        self.assertEqual(canvas.layer_manager.active_layer_id, simulation_layer.id)
        self.assertEqual(panel.current_layer_id(), simulation_layer.id)

        before_x = first.bounding_rect().x()
        panel.offset_x.setValue(5)
        panel.apply_translation()
        self.assertGreater(first.bounding_rect().x(), before_x)

    def test_layer_state_changes_still_refresh_without_canvas_frame_refresh(self):
        canvas = Canvas(500, 300)
        layer = canvas.layer_manager.add("测试层")
        panel = LayerPanel(canvas)
        canvas.layers_changed.emit()
        target = next(panel.list.item(index) for index in range(panel.list.count())
                      if panel.list.item(index).data(Qt.UserRole) == layer.id)
        panel.list.setCurrentItem(target)

        canvas.set_layer_visibility(layer.id, False)

        refreshed = next(panel.list.item(index) for index in range(panel.list.count())
                         if panel.list.item(index).data(Qt.UserRole) == layer.id)
        self.assertEqual(refreshed.checkState(), Qt.Unchecked)


if __name__ == "__main__":
    unittest.main()
