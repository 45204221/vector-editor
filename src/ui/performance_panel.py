"""Runtime performance dock for the editor pipeline."""

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QAbstractItemView, QCheckBox, QFileDialog, QHBoxLayout, QLabel,
    QHeaderView, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)


METRIC_LABELS = {
    "frame_total": "整帧 CPU", "world_total": "世界更新",
    "collision": "碰撞检测", "routing": "连接线路由",
    "render_sync": "渲染同步", "geometry": "几何编译",
    "arena_update": "Arena 更新", "arena_frame": "Arena 命令",
    "upload_plan": "上传计划", "gpu_upload_cpu": "GPU 上传 CPU",
    "backend_render": "后端绘制 CPU", "gpu_draw": "GPU 绘制",
    "pipeline_debug": "管线调试覆盖层",
    "instance_upload": "实例数据构建/上传", "instanced_draw_cpu": "实例 Draw 提交",
    "glyph_atlas_rebuild": "字形 Atlas/顶点重建", "gpu_text_draw_cpu": "GPU 文字提交",
    "visibility_polygon": "可见性多边形/调试绘制", "gpu_lighting": "GPU 光照三 Pass",
}

GAUGE_LABELS = {
    "shape_count": "图元", "visible_shapes": "可见图元",
    "visible_primitives": "可见 Primitive", "gpu_vertices": "GPU 顶点",
    "gpu_batches": "GPU 批次", "upload_bytes": "上传字节",
    "upload_ranges": "上传区间", "dirty_shapes": "Dirty 图元",
    "gpu_allocations": "GPU Allocation", "gpu_fragmentation": "碎片率",
    "collision_candidates": "碰撞候选", "collision_narrow_tests": "窄相检测",
    "routing_expanded_nodes": "路由展开节点", "opengl_fallback": "OpenGL 回退",
    "opengl_msaa_samples": "MSAA 样本", "geometry_backend": "几何内核",
    "instance_count": "实例数量", "instance_bytes": "实例字节",
    "instanced_draw_calls": "实例 Draw Call", "instance_upload_count": "实例上传次数",
    "glyph_count": "唯一字形", "glyph_vertices": "字形顶点",
    "glyph_vbo_bytes": "文字 VBO 字节", "gpu_text_draw_calls": "文字 Draw Call",
    "glyph_upload_count": "字形上传次数",
    "visibility_segments": "遮挡边", "visibility_rays": "可见性射线",
    "visibility_tests": "射线求交次数", "visibility_backend": "可见性内核",
    "lighting_fan_vertices": "光照 Fan 顶点", "lighting_fbo_bytes": "光照 FBO 字节",
    "lighting_draw_calls": "光照 Draw Call", "lighting_upload_count": "光照上传次数",
    "lighting_count": "运行时光源", "visibility_build_count": "可见性构建次数",
    "visibility_cache_hits": "可见性缓存命中",
}


class FrameTimeGraph(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.values = ()
        self.setMinimumHeight(80)

    def set_values(self, values):
        self.values = tuple(float(value) for value in values)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#20252B"))
        if len(self.values) < 2:
            painter.setPen(QColor("#9AA4AE"))
            painter.drawText(self.rect(), Qt.AlignCenter, "等待帧样本")
            return
        width, height = max(1, self.width() - 8), max(1, self.height() - 8)
        scale_max = max(16.67, max(self.values))
        painter.setPen(QPen(QColor("#43D17A"), 1.5))
        previous = None
        for index, value in enumerate(self.values):
            x = 4 + width * index / max(1, len(self.values) - 1)
            y = 4 + height * (1.0 - min(value, scale_max) / scale_max)
            if previous is not None:
                painter.drawLine(int(previous[0]), int(previous[1]), int(x), int(y))
            previous = (x, y)
        painter.setPen(QColor("#9AA4AE"))
        painter.drawText(7, 15, f"0–{scale_max:.1f} ms")


class PerformancePanel(QWidget):
    """Read-only presentation of a PerformanceProfiler snapshot."""

    def __init__(self, profiler, parent=None):
        super().__init__(parent)
        self.profiler = profiler
        self._build_ui()
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.sampling_check = QCheckBox("采样")
        self.sampling_check.setChecked(self.profiler.enabled)
        self.sampling_check.toggled.connect(self._set_sampling)
        controls.addWidget(self.sampling_check)
        clear_button = QPushButton("清空")
        clear_button.clicked.connect(self.clear_samples)
        controls.addWidget(clear_button)
        export_button = QPushButton("导出 JSON")
        export_button.clicked.connect(self.export_report)
        controls.addWidget(export_button)
        controls.addStretch()
        layout.addLayout(controls)

        self.backend_label = QLabel("后端：等待首帧")
        self.backend_label.setWordWrap(True)
        layout.addWidget(self.backend_label)
        self.graph = FrameTimeGraph()
        layout.addWidget(self.graph)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["阶段", "最近 ms", "平均 ms", "P95 ms", "最大 ms", "样本"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, 6):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

        self.gauge_table = QTableWidget(0, 2)
        self.gauge_table.setHorizontalHeaderLabels(["计数/状态", "值"])
        self.gauge_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.gauge_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.gauge_table.verticalHeader().setVisible(False)
        self.gauge_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.gauge_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents)
        self.gauge_table.setMaximumHeight(180)
        layout.addWidget(self.gauge_table)
        self.status_label = QLabel("性能数据不会写入文档或撤销历史")
        layout.addWidget(self.status_label)

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start()
        self.refresh()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def _set_sampling(self, enabled):
        self.profiler.enabled = bool(enabled)
        self.status_label.setText("采样已启用" if enabled else "采样已暂停")

    def clear_samples(self):
        self.profiler.clear()
        self.refresh()
        self.status_label.setText("性能样本已清空")

    @staticmethod
    def _format_value(value):
        return "—" if value is None else f"{value:.3f}"

    def refresh(self):
        snapshot = self.profiler.snapshot()
        summaries = snapshot["summaries"]
        names = [name for name in METRIC_LABELS if name in summaries]
        names.extend(name for name in summaries if name not in METRIC_LABELS)
        self.table.setRowCount(len(names))
        for row, name in enumerate(names):
            summary = summaries[name]
            values = [METRIC_LABELS.get(name, name),
                      self._format_value(summary["latest"]),
                      self._format_value(summary["average"]),
                      self._format_value(summary["p95"]),
                      self._format_value(summary["maximum"]), str(summary["count"])]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.graph.set_values(snapshot["samples_ms"].get("frame_total", ()))
        gauges = snapshot["gauges"]
        self.backend_label.setText(f"后端：{gauges.get('render_backend', '等待首帧')}")
        names = [name for name in GAUGE_LABELS if name in gauges]
        names.extend(name for name in gauges
                     if name not in GAUGE_LABELS and name != "render_backend")
        self.gauge_table.setRowCount(len(names))
        for row, name in enumerate(names):
            value = gauges[name]
            if name == "gpu_fragmentation" and isinstance(value, (int, float)):
                value = f"{value:.1%}"
            self.gauge_table.setItem(
                row, 0, QTableWidgetItem(GAUGE_LABELS.get(name, name)))
            self.gauge_table.setItem(row, 1, QTableWidgetItem(str(value)))

    def export_to(self, file_path):
        self.profiler.export_json(file_path)
        self.status_label.setText(f"已导出：{file_path}")

    def export_report(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出性能报告", "performance-report.json", "JSON (*.json)")
        if not file_path:
            return
        if not file_path.lower().endswith(".json"):
            file_path += ".json"
        try:
            self.export_to(file_path)
        except OSError as error:
            QMessageBox.warning(self, "导出失败", str(error))
