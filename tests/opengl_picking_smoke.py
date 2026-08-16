"""Short real-context smoke test for the M14.1 ID framebuffer/picking path."""

import json
import os
import sys


os.environ.setdefault("QT_OPENGL", "desktop")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtCore import QPointF, QTimer
from PyQt5.QtGui import QColor, QSurfaceFormat
from PyQt5.QtWidgets import QApplication

from ui.main_window import MainWindow


def main():
    surface_format = QSurfaceFormat.defaultFormat()
    surface_format.setSamples(max(4, surface_format.samples()))
    surface_format.setStencilBufferSize(max(8, surface_format.stencilBufferSize()))
    QSurfaceFormat.setDefaultFormat(surface_format)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(900, 650)
    window.canvas.show_grid = False
    lower = window.canvas.create_rectangle(200, 180, 700, 500)
    lower.fill_color = QColor(40, 140, 230)
    upper = window.canvas.create_ellipse(500, 320, 650, 520)
    upper.fill_color = QColor(245, 90, 100)
    window.canvas.add_shape(lower)
    window.canvas.add_shape(upper)
    window.show()
    view = window.graphics_view
    view.set_render_backend("opengl")
    app.processEvents()
    view.fit_to_window()
    view.set_picking_mode("compare")

    samples = [
        (QPointF(100, 100), ""),
        (QPointF(300, 250), lower.id),
        (QPointF(650, 450), upper.id),
    ]

    def verify():
        backend = view.render_item.backend
        results = []
        failures = []
        viewport = view.viewport()
        viewport.makeCurrent()
        try:
            for scene_point, expected in samples:
                widget_point = view.mapFromScene(scene_point)
                width, height = backend.id_target_size
                x = widget_point.x() * width / max(1, viewport.width())
                y = widget_point.y() * height / max(1, viewport.height())
                picked, elapsed_ms, error = backend.pick_device_pixel(x, y)
                row = {
                    "scene": (scene_point.x(), scene_point.y()),
                    "expected": expected, "gpu": picked or "",
                    "readback_ms": elapsed_ms, "error": error,
                }
                results.append(row)
                if error or (picked or "") != expected:
                    failures.append(row)
            image = backend.id_attachment_image()
        finally:
            viewport.doneCurrent()

        overlap = samples[-1][0]
        overlap_widget = view.mapFromScene(overlap)
        selected = view.hit_test_for_selection(overlap, overlap_widget)
        state = backend.offscreen_state()
        if selected is not upper or not state["matched"]:
            failures.append({"selection": selected.id if selected else "", "state": state})
        if (backend.fallback_active or backend.last_error or not state["target_valid"]
                or state["mapped_shapes"] != 2 or image is None or image.isNull()):
            failures.append({
                "fallback": backend.fallback_active, "error": backend.last_error,
                "state": state, "image_null": image is None or image.isNull(),
            })
        print(json.dumps({
            "results": results, "state": state,
            "target_image": (image.width(), image.height()) if image else (0, 0),
            "failures": failures,
        }, ensure_ascii=False, indent=2))
        window.close()
        app.exit(1 if failures else 0)

    QTimer.singleShot(700, verify)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
