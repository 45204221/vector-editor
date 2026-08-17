"""Independent paged workspace for advanced engine/rendering experiments."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QMainWindow, QTabWidget, QVBoxLayout, QWidget

from .performance_panel import PerformancePanel
from .pipeline_panel import PipelinePanel
from .instancing_panel import InstancingPanel
from .lighting_panel import LightingPanel
from .pipeline3d_panel import Pipeline3DPanel
from .texture_sampling_panel import TextureSamplingPanel


class EngineLabWindow(QMainWindow):
    """Non-modal advanced workspace sharing the editor's live runtime state."""

    PIPELINE_PAGE = 0
    PERFORMANCE_PAGE = 1
    INSTANCING_PAGE = 2
    LIGHTING_PAGE = 3
    PIPELINE3D_PAGE = 4
    TEXTURE_SAMPLING_PAGE = 5

    def __init__(self, canvas, graphics_view, parent=None):
        super().__init__(parent, Qt.Window)
        self.canvas = canvas
        self.graphics_view = graphics_view
        self.setWindowTitle("引擎实验室")
        self.setMinimumSize(900, 620)
        self.resize(1280, 820)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        source_label = QLabel(
            "实时连接当前编辑画布 · 实验配置不写入文档、保存或撤销历史")
        source_label.setObjectName("engine_lab_source_label")
        source_label.setWordWrap(True)
        layout.addWidget(source_label)

        self.pages = QTabWidget()
        self.pages.setObjectName("engine_lab_pages")
        self.pages.setDocumentMode(True)
        self.pages.tabBar().setExpanding(False)
        self.pages.tabBar().setUsesScrollButtons(True)
        self.pages.tabBar().setElideMode(Qt.ElideRight)
        layout.addWidget(self.pages, 1)

        self.pipeline_panel = PipelinePanel(graphics_view)
        self.performance_panel = PerformancePanel(canvas.profiler)
        self.instancing_panel = InstancingPanel(graphics_view)
        self.lighting_panel = LightingPanel(graphics_view)
        self.pipeline3d_panel = Pipeline3DPanel(canvas)
        self.texture_sampling_panel = TextureSamplingPanel(canvas)
        self.pages.addTab(self.pipeline_panel, "渲染管线")
        self.pages.addTab(self.performance_panel, "性能分析")
        self.pages.addTab(self.instancing_panel, "Atlas/实例化")
        self.pages.addTab(self.lighting_panel, "2D 光照/阴影")
        self.pages.addTab(self.pipeline3d_panel, "3D 渲染管线")
        self.pages.addTab(self.texture_sampling_panel, "纹理采样/LOD")
        self.pages.currentChanged.connect(self._refresh_current_page)
        self.setCentralWidget(central)

    def show_page(self, page="pipeline"):
        index = {
            "pipeline": self.PIPELINE_PAGE,
            "performance": self.PERFORMANCE_PAGE,
            "instancing": self.INSTANCING_PAGE,
            "lighting": self.LIGHTING_PAGE,
            "pipeline3d": self.PIPELINE3D_PAGE,
            "texture_sampling": self.TEXTURE_SAMPLING_PAGE,
        }.get(page)
        if index is None:
            raise ValueError(f"Unknown engine lab page: {page}")
        self.pages.setCurrentIndex(index)
        self.show()
        self.raise_()
        self.activateWindow()
        self._refresh_current_page(index)

    def _refresh_current_page(self, index):
        if index == self.PIPELINE_PAGE:
            self.pipeline_panel.refresh()
        elif index == self.PERFORMANCE_PAGE:
            self.performance_panel.refresh()
        elif index == self.INSTANCING_PAGE:
            self.instancing_panel.refresh()
        elif index == self.LIGHTING_PAGE:
            self.lighting_panel.refresh()
        elif index == self.PIPELINE3D_PAGE:
            self.pipeline3d_panel.refresh()
        elif index == self.TEXTURE_SAMPLING_PAGE:
            self.texture_sampling_panel.refresh()

    def closeEvent(self, event):
        # Preserve selected tabs, previews and sampling state between openings.
        event.ignore()
        self.hide()
