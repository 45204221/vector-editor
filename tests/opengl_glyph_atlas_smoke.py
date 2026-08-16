"""Real-context smoke test for M15.2 glyph atlas GPU text rendering."""

import json
import os
import sys


os.environ.setdefault("QT_OPENGL", "desktop")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtCore import QPoint, QTimer
from PyQt5.QtGui import QSurfaceFormat
from PyQt5.QtWidgets import QApplication

from ui.main_window import MainWindow


def text_region_dark_pixels(window, view, image, shapes):
    scale_x = image.width() / max(1, window.width())
    scale_y = image.height() / max(1, window.height())
    origin = view.viewport().mapTo(window, QPoint(0, 0))
    count = 0
    for shape in shapes:
        rect = view.viewportTransform().mapRect(shape.bounding_rect()).adjusted(-3, -3, 3, 3)
        left = max(0, int((origin.x() + rect.left()) * scale_x))
        right = min(image.width(), int((origin.x() + rect.right()) * scale_x) + 1)
        top = max(0, int((origin.y() + rect.top()) * scale_y))
        bottom = min(image.height(), int((origin.y() + rect.bottom()) * scale_y) + 1)
        for y in range(top, bottom):
            for x in range(left, right):
                color = image.pixelColor(x, y)
                if min(color.red(), color.green(), color.blue()) < 160:
                    count += 1
    return count


def main():
    surface_format = QSurfaceFormat.defaultFormat()
    surface_format.setSamples(max(4, surface_format.samples()))
    surface_format.setStencilBufferSize(max(8, surface_format.stencilBufferSize()))
    QSurfaceFormat.setDefaultFormat(surface_format)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(960, 680)
    window.canvas.show_grid = False
    before = window.canvas.create_rectangle(40, 40, 100, 60)
    first = window.canvas.create_text(180, 100, "GPU Text 中文")
    first.font_size = 28
    second = window.canvas.create_text(180, 190, "Atlas\n第二行")
    second.font_size = 22
    after = window.canvas.create_ellipse(500, 320, 120, 90)
    for shape in (before, first, second, after):
        window.canvas.add_shape(shape)
    window.show()
    view = window.graphics_view
    view.set_render_backend("opengl")
    view.fit_to_window()
    window.show_instancing_panel()
    view.set_gpu_text_experiment(True)

    results = {}
    failures = []

    def check_initial():
        backend = view.render_item.backend
        state = view.gpu_text_experiment_state()
        results["initial"] = dict(state)
        gpu_image = app.primaryScreen().grabWindow(window.winId()).toImage()
        capture_path = os.environ.get("GLYPH_CAPTURE")
        if capture_path:
            app.primaryScreen().grabWindow(window.winId()).save(capture_path, "PNG")
        results["gpu_dark_pixels"] = text_region_dark_pixels(
            window, view, gpu_image, (first, second))
        if (not state["resources_valid"] or state["unique_glyphs"] < 8
                or state["rendered_glyphs"] < 10
                or state["vertices"] != state["rendered_glyphs"] * 6
                or state["vbo_bytes"] != state["vertices"] * 32
                or state["draw_calls"] != 2 or state["upload_count"] != 1
                or state["fallback_commands"] or state["error"]
                or backend.fallback_active or backend.last_error):
            failures.append({"initial": state, "fallback": backend.fallback_active,
                             "backend_error": backend.last_error})
        view.set_gpu_text_experiment(False)
        QTimer.singleShot(180, check_qt_reference)

    def check_qt_reference():
        qt_image = app.primaryScreen().grabWindow(window.winId()).toImage()
        capture_path = os.environ.get("GLYPH_CAPTURE")
        if capture_path:
            app.primaryScreen().grabWindow(window.winId()).save(
                capture_path + ".qt.png", "PNG")
        qt_pixels = text_region_dark_pixels(window, view, qt_image, (first, second))
        gpu_pixels = results["gpu_dark_pixels"]
        results["qt_dark_pixels"] = qt_pixels
        if gpu_pixels <= 0 or qt_pixels <= 0 or gpu_pixels < qt_pixels * 0.25:
            failures.append({"visual_pixels": {"gpu": gpu_pixels, "qt": qt_pixels}})
        view.set_gpu_text_experiment(True)
        view.zoom_in()
        QTimer.singleShot(250, check_zoom)

    def check_zoom():
        state = view.gpu_text_experiment_state()
        results["zoom"] = dict(state)
        if state["upload_count"] != results["initial"]["upload_count"]:
            failures.append({"zoom_reuploaded": state})
        third = window.canvas.create_text(180, 280, "新增 Glyph 3")
        third.font_size = 20
        window.canvas.add_shape(third)
        QTimer.singleShot(300, check_document_change)

    def check_document_change():
        state = view.gpu_text_experiment_state()
        results["document_change"] = dict(state)
        if (state["upload_count"] != 2 or state["atlas_rebuild_count"] != 2
                or state["draw_calls"] != 3 or state["fallback_commands"]
                or state["error"]):
            failures.append({"document_change": state})
        view.set_gpu_text_experiment(False)
        QTimer.singleShot(180, check_disabled)

    def check_disabled():
        state = view.gpu_text_experiment_state()
        results["disabled"] = dict(state)
        if state["enabled"] or state["draw_calls"] != 0:
            failures.append({"disabled": state})
        view.set_gpu_text_experiment(True)
        QTimer.singleShot(180, check_reenabled)

    def check_reenabled():
        state = view.gpu_text_experiment_state()
        results["reenabled"] = dict(state)
        if state["draw_calls"] != 3 or state["upload_count"] != 2:
            failures.append({"reenabled": state})
        view.set_render_backend("command")
        preserved = view.gpu_text_experiment_state()
        if not preserved["enabled"]:
            failures.append({"command_preserved": preserved})
        view.set_render_backend("opengl")
        QTimer.singleShot(450, check_rebuilt)

    def check_rebuilt():
        backend = view.render_item.backend
        state = view.gpu_text_experiment_state()
        results["rebuilt"] = dict(state)
        if (not state["resources_valid"] or state["draw_calls"] != 3
                or state["upload_count"] != 1 or state["error"]
                or backend.fallback_active or backend.last_error):
            failures.append({"rebuilt": state, "fallback": backend.fallback_active,
                             "backend_error": backend.last_error})
        print(json.dumps({"results": results, "failures": failures},
                         ensure_ascii=False, indent=2))
        window.close()
        app.exit(1 if failures else 0)

    QTimer.singleShot(700, check_initial)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
