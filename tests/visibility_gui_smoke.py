"""Short real-window smoke test for M16.1 visibility debug integration."""

import json
import os
import sys


os.environ.setdefault("QT_OPENGL", "desktop")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QSurfaceFormat
from PyQt5.QtWidgets import QApplication

from ui.main_window import MainWindow


def debug_pixel_count(image):
    count = 0
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            color = image.pixelColor(x, y)
            if color.red() > 180 and color.green() < 175 and color.blue() < 180:
                count += 1
    return count


def main():
    surface_format = QSurfaceFormat.defaultFormat()
    surface_format.setSamples(max(4, surface_format.samples()))
    surface_format.setStencilBufferSize(max(8, surface_format.stencilBufferSize()))
    QSurfaceFormat.setDefaultFormat(surface_format)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1000, 700)
    window.canvas.show_grid = False
    for shape in (window.canvas.create_rectangle(430, 240, 320, 180),
                  window.canvas.create_rectangle(1050, 700, 280, 260)):
        window.canvas.add_shape(shape)
    window.show()
    view = window.graphics_view
    view.fit_to_window()
    window.show_lighting_panel()
    view.set_lighting_experiment(
        enabled=True, light_x=780, light_y=520, radius=480,
        debug_mode="combined", use_native=True)
    document_state = window.canvas._capture_document_state()
    history = window.canvas.history_manager.current_index
    backends = ["legacy", "command", "opengl"]
    results = []
    failures = []

    def step(index=0):
        if index >= len(backends):
            before = view.lighting_snapshot()
            old_polygon = before.result.polygon
            view.zoom_in()
            app.processEvents()
            if view.lighting_snapshot() is not before:
                failures.append({"zoom_recomputed": True})
            view.set_lighting_experiment(light_x=920, light_y=610)
            moved = view.lighting_snapshot()
            if moved.result.polygon == old_polygon:
                failures.append({"light_move_unchanged": True})
            if (window.canvas._capture_document_state() != document_state or
                    window.canvas.history_manager.current_index != history):
                failures.append({"document_mutated": True})
            if window.engine_lab_window.pages.currentIndex() != 3:
                failures.append({"lab_page": window.engine_lab_window.pages.currentIndex()})
            print(json.dumps({"results": results, "failures": failures},
                             ensure_ascii=False, indent=2))
            window.close()
            app.exit(1 if failures else 0)
            return
        backend_name = backends[index]
        view.set_render_backend(backend_name)

        def record():
            state = view.lighting_experiment_state()
            image = app.primaryScreen().grabWindow(window.winId()).toImage()
            pixels = debug_pixel_count(image)
            backend = view.render_item.backend
            item = {"backend": backend_name, "state": state,
                    "debug_pixels": pixels,
                    "fallback": bool(getattr(backend, "fallback_active", False)),
                    "error": str(getattr(backend, "last_error", ""))}
            results.append(item)
            if (state["backend"] != "C++ native" or state["segments"] != 12
                    or state["rays"] <= 0 or state["polygon_points"] <= 0
                    or state["intersection_tests"] <= 0 or pixels <= 10
                    or item["fallback"] or item["error"]):
                failures.append(item)
            step(index + 1)

        QTimer.singleShot(350 if backend_name == "opengl" else 180, record)

    QTimer.singleShot(300, step)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
