import os
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QApplication, QDockWidget, QScrollArea,
                             QSplitter, QTabWidget)

from ui.main_window import MainWindow


APP = QApplication.instance() or QApplication([])


class WorkspaceLayoutTests(unittest.TestCase):
    def setUp(self):
        self.window = MainWindow()
        self.window.show()
        APP.processEvents()

    def tearDown(self):
        self.window.engine_lab_window.hide()
        self.window.close()
        APP.processEvents()

    def test_main_window_keeps_only_basic_editor_docks(self):
        self.assertGreaterEqual(self.window.minimumWidth(), 900)
        self.assertGreaterEqual(self.window.minimumHeight(), 600)
        docks = set(self.window.findChildren(QDockWidget))
        self.assertEqual(docks, {self.window.properties_dock, self.window.layers_dock})
        self.assertEqual(set(self.window.tabifiedDockWidgets(
            self.window.properties_dock)), {self.window.layers_dock})
        for dock in docks:
            self.assertEqual(dock.allowedAreas(), Qt.RightDockWidgetArea)
            self.assertGreaterEqual(dock.minimumWidth(), 300)
        self.assertIsInstance(self.window.layers_dock.widget(), QScrollArea)

    def test_engine_lab_owns_advanced_paged_panels(self):
        lab = self.window.engine_lab_window
        self.assertFalse(lab.isVisible())
        self.assertEqual(lab.pages.count(), 6)
        self.assertEqual(lab.pages.tabText(0), "渲染管线")
        self.assertEqual(lab.pages.tabText(1), "性能分析")
        self.assertEqual(lab.pages.tabText(2), "Atlas/实例化")
        self.assertEqual(lab.pages.tabText(3), "2D 光照/阴影")
        self.assertEqual(lab.pages.tabText(4), "3D 渲染管线")
        self.assertEqual(lab.pages.tabText(5), "纹理采样/LOD")
        self.assertIs(self.window.pipeline_panel, lab.pipeline_panel)
        self.assertIs(self.window.performance_panel, lab.performance_panel)
        self.assertIs(self.window.lighting_panel, lab.lighting_panel)
        self.assertIs(self.window.pipeline3d_panel, lab.pipeline3d_panel)
        self.assertIsNotNone(lab.pipeline_panel.findChild(
            QScrollArea, "shader_experiment_scroll"))
        self.assertIsNotNone(lab.pipeline_panel.findChild(
            QScrollArea, "offscreen_experiment_scroll"))

    def test_pipeline3d_uses_responsive_categorized_property_pages(self):
        lab = self.window.engine_lab_window
        panel = lab.pipeline3d_panel
        tabs = panel.property_tabs
        splitter = panel.findChild(QSplitter, "pipeline3d_splitter")
        self.assertGreaterEqual(lab.minimumWidth(), 900)
        self.assertGreaterEqual(lab.minimumHeight(), 620)
        self.assertIsInstance(tabs, QTabWidget)
        self.assertEqual(tabs.count(), 5)
        self.assertEqual([tabs.tabText(index) for index in range(5)],
                         ["场景/相机", "光照/阴影", "附件/G-buffer",
                          "追踪/统计", "CPU/OpenGL"])
        self.assertTrue(all(isinstance(tabs.widget(index), QScrollArea)
                            for index in range(tabs.count())))
        self.assertIsNotNone(splitter)
        self.assertFalse(splitter.childrenCollapsible())
        self.assertGreaterEqual(tabs.minimumWidth(), 360)

        lab.resize(900, 620); self.window.show_pipeline3d_panel()
        APP.processEvents()
        self.assertTrue(panel.viewport.isVisible())
        self.assertTrue(tabs.isVisible())
        self.assertGreaterEqual(tabs.width(), 350)
        tabs.setCurrentIndex(2); lab.close(); APP.processEvents()
        self.window.show_pipeline3d_panel(); APP.processEvents()
        self.assertEqual(tabs.currentIndex(), 2)

    def test_show_close_and_reopen_preserve_page_and_runtime_identity(self):
        revision = self.window.canvas.render_revision
        history = self.window.canvas.history_manager.current_index
        backend = self.window.graphics_view.render_item.backend
        lab = self.window.engine_lab_window

        self.window.show_performance_panel()
        APP.processEvents()
        self.assertTrue(lab.isVisible())
        self.assertEqual(lab.pages.currentIndex(), 1)
        lab.close()
        APP.processEvents()
        self.assertFalse(lab.isVisible())
        self.window.show_performance_panel()
        APP.processEvents()

        self.assertEqual(lab.pages.currentIndex(), 1)
        self.assertEqual(self.window.canvas.render_revision, revision)
        self.assertEqual(self.window.canvas.history_manager.current_index, history)
        self.assertIs(self.window.graphics_view.render_item.backend, backend)

    def test_pipeline_page_switch_keeps_nested_experiment_pages(self):
        lab = self.window.engine_lab_window
        lab.pipeline_panel.tabs.setCurrentIndex(4)
        self.window.show_pipeline_panel()
        APP.processEvents()

        self.assertEqual(lab.pages.currentIndex(), 0)
        self.assertEqual(lab.pipeline_panel.tabs.currentIndex(), 4)
        self.assertTrue(lab.pipeline_panel.tabs.tabBar().usesScrollButtons())

    def test_closing_main_window_also_hides_lab_window(self):
        self.window.show_pipeline_panel()
        APP.processEvents()
        self.assertTrue(self.window.engine_lab_window.isVisible())

        self.window.close()
        APP.processEvents()

        self.assertFalse(self.window.engine_lab_window.isVisible())


if __name__ == "__main__":
    unittest.main()
