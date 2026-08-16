import json
import os
import sys
import tempfile
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtWidgets import QApplication

from core.canvas import Canvas
from core.profiling import PerformanceProfiler
from ui.main_window import MainWindow
from ui.performance_panel import PerformancePanel


class PerformanceProfilerTests(unittest.TestCase):
    def test_ring_buffer_and_summary_are_bounded(self):
        profiler = PerformanceProfiler(capacity=3)
        for value in (1.0, 2.0, 3.0, 4.0):
            profiler.record_ms("frame_total", value)

        snapshot = profiler.snapshot()
        self.assertEqual(snapshot["samples_ms"]["frame_total"], [2.0, 3.0, 4.0])
        summary = snapshot["summaries"]["frame_total"]
        self.assertEqual(summary["count"], 3)
        self.assertEqual(summary["latest"], 4.0)
        self.assertEqual(summary["average"], 3.0)
        self.assertEqual(summary["p95"], 4.0)

    def test_disabled_profiler_does_not_collect_and_measure_is_exception_safe(self):
        profiler = PerformanceProfiler()
        profiler.enabled = False
        with profiler.measure("disabled"):
            pass
        self.assertEqual(profiler.samples("disabled"), ())

        profiler.enabled = True
        with self.assertRaisesRegex(RuntimeError, "expected"):
            with profiler.measure("failed"):
                raise RuntimeError("expected")
        self.assertEqual(len(profiler.samples("failed")), 1)

    def test_json_report_contains_environment_gauges_and_samples(self):
        profiler = PerformanceProfiler()
        profiler.record_ms("frame_total", 1.25)
        profiler.set_gauge("gpu_batches", 3)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "report.json")
            profiler.export_json(path)
            with open(path, "r", encoding="utf-8") as report:
                payload = json.load(report)

        self.assertEqual(payload["schema_version"], 1)
        self.assertIn("python", payload["metadata"])
        self.assertEqual(payload["gauges"]["gpu_batches"], 3)
        self.assertEqual(payload["samples_ms"]["frame_total"], [1.25])

    def test_canvas_records_world_collision_and_routing_stages(self):
        canvas = Canvas(500, 400)
        shape = canvas.create_rectangle(20, 20, 40, 40)
        canvas.add_shape(shape)
        canvas.update_world_state()

        self.assertEqual(len(canvas.profiler.samples("world_total")), 2)
        self.assertEqual(len(canvas.profiler.samples("collision")), 2)
        self.assertEqual(len(canvas.profiler.samples("routing")), 2)
        self.assertEqual(canvas.profiler.snapshot()["gauges"]["shape_count"], 1)


class PerformancePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_panel_refresh_and_clear_do_not_touch_document_history(self):
        canvas = Canvas(500, 400)
        canvas.profiler.record_ms("frame_total", 2.0)
        canvas.profiler.set_gauge("gpu_batches", 7)
        history_index = canvas.history_manager.current_index
        panel = PerformancePanel(canvas.profiler)
        panel.refresh()

        self.assertEqual(panel.table.rowCount(), 1)
        self.assertEqual(panel.gauge_table.rowCount(), 1)
        self.assertEqual(panel.gauge_table.item(0, 0).text(), "GPU 批次")
        self.assertEqual(panel.gauge_table.item(0, 1).text(), "7")
        self.assertEqual(canvas.history_manager.current_index, history_index)
        panel.clear_samples()
        self.assertEqual(panel.table.rowCount(), 0)
        self.assertEqual(canvas.history_manager.current_index, history_index)

    def test_performance_page_lives_in_engine_lab_and_can_be_raised(self):
        window = MainWindow()
        window.resize(800, 600)
        window.show()
        self.app.processEvents()
        self.assertFalse(window.engine_lab_window.isVisible())
        tabified = set(window.tabifiedDockWidgets(window.properties_dock))
        self.assertEqual(tabified, {window.layers_dock})
        for dock in (window.properties_dock, window.layers_dock):
            self.assertIn(dock.toggleViewAction(), self._view_actions(window))

        window.show_performance_panel()
        self.app.processEvents()
        self.assertTrue(window.engine_lab_window.isVisible())
        self.assertEqual(window.engine_lab_window.pages.currentIndex(), 1)
        geometry = window.engine_lab_window.geometry()
        self.assertGreaterEqual(geometry.left(), 0)
        self.assertGreaterEqual(geometry.top(), 0)
        self.assertGreaterEqual(geometry.width(), 820)
        self.assertGreaterEqual(geometry.height(), 600)
        window.engine_lab_window.close()
        window.close()

    @staticmethod
    def _view_actions(window):
        return window.view_menu.actions()


if __name__ == "__main__":
    unittest.main()
