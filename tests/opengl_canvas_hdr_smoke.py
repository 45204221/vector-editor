"""Real-context smoke test for M20.1 live canvas HDR postprocessing."""

import hashlib
import json
import os
import sys


os.environ.setdefault("QT_OPENGL", "desktop")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QImage, QSurfaceFormat
from PyQt5.QtWidgets import QApplication
from ui.main_window import MainWindow


def signature(image):
    converted = image.convertToFormat(QImage.Format_RGBA8888)
    pointer = converted.bits(); pointer.setsize(converted.byteCount())
    payload = bytes(pointer)
    return ((converted.width(), converted.height()),
            hashlib.sha1(payload).hexdigest()[:16])


def sampled_nontransparent(image):
    count = 0
    for y in range(0, image.height(), max(1, image.height() // 64)):
        for x in range(0, image.width(), max(1, image.width() // 64)):
            count += int(image.pixelColor(x, y).alpha() > 0)
    return count


def main():
    format_ = QSurfaceFormat.defaultFormat()
    format_.setSamples(max(4, format_.samples()))
    format_.setStencilBufferSize(max(8, format_.stencilBufferSize()))
    QSurfaceFormat.setDefaultFormat(format_)
    app = QApplication.instance() or QApplication([])
    window = MainWindow(); window.resize(980, 700)
    window.canvas.show_grid = True
    first = window.canvas.create_rectangle(120, 120, 640, 420)
    first.style.brush_color = "#FF8A24"; first.style.opacity = 0.92
    second = window.canvas.create_ellipse(420, 270, 580, 430)
    second.style.brush_color = "#4CC9FF"; second.style.opacity = 0.88
    window.canvas.add_shape(first); window.canvas.add_shape(second)
    window.show(); view = window.graphics_view
    view.set_render_backend("opengl"); view.fit_to_window(); app.processEvents()
    view.set_raster_experiment("screen_gradient", "additive", "none")
    revision = window.canvas.render_revision
    history = window.canvas.history_manager.current_index
    cases = ((False, "reinhard", 1.0, "final"),
             (True, "linear", 3.0, "final"),
             (True, "reinhard", 3.0, "final"),
             (True, "aces", 3.0, "final"),
             (True, "aces", 3.0, "heatmap"),
             (True, "aces", 3.0, "overexposure"))
    report, failures = {}, []

    def run_case(index=0):
        if index >= len(cases):
            old_size = view.render_item.backend.hdr_target_size
            view.set_raster_experiment("screen_gradient", "additive", "stencil")
            window.resize(1120, 760); view.scene.update()
            QTimer.singleShot(350, lambda: finish(old_size))
            return
        enabled, operator, exposure, debug = cases[index]
        view.set_canvas_hdr(enabled, operator, exposure, debug)
        view.viewport().update(); view.scene.update()
        QTimer.singleShot(220, lambda: capture(index, cases[index]))

    def capture(index, case):
        image = view.viewport().grab().toImage()
        if case[0]:
            viewport = view.viewport(); viewport.makeCurrent()
            try:
                diagnostic = view.render_item.backend.render_hdr_attachment()
                if diagnostic is not None and not diagnostic.isNull():
                    image = diagnostic
            finally:
                viewport.doneCurrent()
        report[str(case)] = signature(image)
        run_case(index + 1)

    def finish(old_size):
        backend = view.render_item.backend
        state = backend.hdr_state()
        raster_state = backend.experiment_state()
        viewport = view.viewport(); viewport.makeCurrent()
        try:
            hdr_image = backend.hdr_target.toImage() if backend.hdr_target else QImage()
        finally:
            viewport.doneCurrent()
        signatures = set(report.values())
        uploads_before = backend.full_upload_count + backend.partial_upload_count
        view.set_canvas_hdr(True, "reinhard", 2.0, "final")
        app.processEvents()
        uploads_after = backend.full_upload_count + backend.partial_upload_count
        valid = (state["target_valid"] and not hdr_image.isNull()
                 and sampled_nontransparent(hdr_image) > 0
                 and state["target_format"].startswith("RGBA16F")
                 and tuple(state["target_size"]) != tuple(old_size)
                 and raster_state["effective_clip_mode"] == "stencil"
                 and state["passes"] == 2 and state["frames"] >= 5
                 and not state["error"] and len(signatures) == len(cases)
                 and uploads_before == uploads_after
                 and window.canvas.render_revision == revision
                 and window.canvas.history_manager.current_index == history)
        if not valid:
            failures.append({"state": state, "raster_state": raster_state,
                             "signatures": report,
                             "uploads": (uploads_before, uploads_after),
                             "revision": (revision, window.canvas.render_revision),
                             "history": (history,
                                         window.canvas.history_manager.current_index)})
        print(json.dumps({"report": report, "hdr_source": (
                              signature(hdr_image), sampled_nontransparent(hdr_image)),
                          "state": state,
                          "raster_state": raster_state,
                          "failures": failures}, ensure_ascii=False, indent=2))
        window.close(); app.exit(1 if failures else 0)

    QTimer.singleShot(900, run_case)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
