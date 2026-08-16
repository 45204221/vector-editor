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
from core.opengl_backend import OpenGLBackend
from core.pipeline_debug import PipelineDebugMode, build_pipeline_snapshot
from core.rendering import CommandQPainterBackend
from ui.main_window import MainWindow


APP = QApplication.instance() or QApplication([])


class PipelineSnapshotTests(unittest.TestCase):
    def _command_scene(self):
        canvas = Canvas(200, 100)
        canvas.show_grid = False
        canvas.show_engine_debug = False
        shape = canvas.create_rectangle(20, 10, 40, 30)
        canvas.add_shape(shape)
        backend = CommandQPainterBackend(canvas)
        backend.sync_document(canvas.consume_render_delta(force_full=True), 0)
        return canvas, shape, backend

    def test_selected_shape_traces_real_geometry_and_coordinate_spaces(self):
        canvas, shape, backend = self._command_scene()
        snapshot = build_pipeline_snapshot(
            canvas, backend, QTransform(), (200, 100), (0, 0, 200, 100), shape.id,
            PipelineDebugMode.BATCH.value)

        self.assertEqual(snapshot.selected_shape_id, shape.id)
        self.assertEqual(len(snapshot.primitive_traces), 2)
        first_vertex = snapshot.primitive_traces[0].vertices[0]
        self.assertEqual(first_vertex.local, (20.0, 10.0))
        self.assertEqual(first_vertex.world, (20.0, 10.0))
        self.assertEqual(first_vertex.device, (20.0, 10.0))
        self.assertAlmostEqual(first_vertex.ndc[0], -0.8)
        self.assertAlmostEqual(first_vertex.ndc[1], 0.8)
        self.assertGreater(len(snapshot.primitive_triangles), 2)
        self.assertIn("24 bytes", snapshot.vertex_layout)

    def test_snapshot_and_modes_do_not_mutate_document_or_history(self):
        canvas, shape, backend = self._command_scene()
        revision = canvas.render_revision
        history_index = canvas.history_manager.current_index
        document = canvas.create_render_snapshot()

        for mode in PipelineDebugMode:
            snapshot = build_pipeline_snapshot(
                canvas, backend, QTransform(), (200, 100), (0, 0, 200, 100),
                shape.id if mode != PipelineDebugMode.FINAL else None, mode.value)
            self.assertEqual(snapshot.revision, backend.cache.revision)

        self.assertEqual(canvas.render_revision, revision)
        self.assertEqual(canvas.history_manager.current_index, history_index)
        self.assertEqual(canvas.create_render_snapshot(), document)

    def test_opengl_snapshot_prefers_live_arena_layout(self):
        canvas = Canvas(200, 100)
        shape = canvas.create_rectangle(20, 10, 40, 30)
        canvas.add_shape(shape)
        backend = OpenGLBackend(canvas)
        backend.sync_document(canvas.consume_render_delta(force_full=True), 0)

        snapshot = build_pipeline_snapshot(
            canvas, backend, QTransform(), (200, 100), (0, 0, 200, 100), shape.id,
            PipelineDebugMode.BATCH.value)

        state = dict(snapshot.state)
        self.assertEqual(state["GPU 数据来源"], "live GpuArena/VBO layout")
        self.assertEqual(int(state["Arena allocations"]), backend.arena.allocation_count)
        self.assertGreater(len(snapshot.batch_triangles), 0)


class PipelinePanelTests(unittest.TestCase):
    def test_engine_lab_pipeline_page_and_mode_switch_are_history_neutral(self):
        window = MainWindow()
        window.resize(800, 600)
        window.show()
        APP.processEvents()
        history_index = window.canvas.history_manager.current_index
        revision = window.canvas.render_revision

        self.assertFalse(window.engine_lab_window.isVisible())
        window.show_pipeline_panel()
        APP.processEvents()
        index = window.pipeline_panel.mode_combo.findData(PipelineDebugMode.WIREFRAME.value)
        window.pipeline_panel.mode_combo.setCurrentIndex(index)
        APP.processEvents()

        self.assertTrue(window.engine_lab_window.isVisible())
        self.assertEqual(window.engine_lab_window.pages.currentIndex(), 0)
        self.assertEqual(window.graphics_view.render_item.pipeline_mode, "wireframe")
        self.assertEqual(window.canvas.history_manager.current_index, history_index)
        self.assertEqual(window.canvas.render_revision, revision)
        self.assertEqual(window.pipeline_panel.stage_table.rowCount(), 9)
        window.engine_lab_window.close()
        self.assertFalse(window.engine_lab_window.isVisible())
        window.close()


if __name__ == "__main__":
    unittest.main()
