"""Real-context smoke for the shared M21.1 3D HDR display transform."""

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
from PyQt5.QtGui import QSurfaceFormat
from PyQt5.QtWidgets import QApplication

from ui.main_window import MainWindow


def signature(image):
    if image is None or image.isNull():
        return ""
    return hashlib.sha1(bytes(image.bits().asstring(image.byteCount()))).hexdigest()[:16]


def main():
    surface = QSurfaceFormat.defaultFormat()
    surface.setDepthBufferSize(max(24, surface.depthBufferSize()))
    surface.setStencilBufferSize(max(8, surface.stencilBufferSize()))
    QSurfaceFormat.setDefaultFormat(surface)
    app = QApplication.instance() or QApplication([])
    window = MainWindow(); window.resize(960, 700); window.show()
    window.show_pipeline3d_panel()
    panel = window.pipeline3d_panel
    lab = window.engine_lab_window; lab.resize(1100, 780)
    viewport = panel.viewport
    cases = (("forward", "linear", "final", False),
             ("forward", "reinhard", "final", False),
             ("forward", "aces", "final", False),
             ("forward", "aces", "final", True),
             ("forward", "aces", "heatmap", True),
             ("deferred", "aces", "final", True),
             ("deferred", "aces", "overexposure", True))
    report, failures = {}, []

    def begin():
        report["baseline"] = viewport.runtime_state()
        report["upload"] = viewport.upload_count
        report["revision"] = window.canvas.render_revision
        report["history"] = window.canvas.history_manager.current_index
        panel.hdr_enabled_check.setChecked(True)
        panel.hdr_exposure_spin.setValue(3.0)
        run_case(0)

    def run_case(index):
        if index >= len(cases):
            QTimer.singleShot(150, auto_start)
            return
        path, tone, debug, bloom = cases[index]
        panel.render_path_combo.setCurrentIndex(
            panel.render_path_combo.findData(path))
        panel.hdr_tone_combo.setCurrentIndex(panel.hdr_tone_combo.findData(tone))
        panel.hdr_debug_combo.setCurrentIndex(panel.hdr_debug_combo.findData(debug))
        panel.bloom_enabled_check.setChecked(bloom)

        def capture():
            report[str(cases[index])] = signature(viewport.grabFramebuffer())
            run_case(index + 1)
        QTimer.singleShot(260, capture)

    def auto_start():
        panel.auto_exposure_check.setChecked(True)
        panel.exposure_compensation_spin.setValue(-1.0)
        QTimer.singleShot(900, auto_done)

    def auto_done():
        report["auto_signature"] = signature(viewport.grabFramebuffer())
        finish()

    def finish():
        scene = viewport.render_attachment("hdr_scene")
        bloom_near = viewport.render_attachment("bloom_near")
        bloom_far = viewport.render_attachment("bloom_far")
        final = viewport.render_attachment("hdr_final")
        state = viewport.runtime_state()
        report["state"] = state
        report["attachments"] = {
            "scene": ((scene.width(), scene.height()), signature(scene)) if scene else None,
            "bloom_near": ((bloom_near.width(), bloom_near.height()),
                           signature(bloom_near)) if bloom_near else None,
            "bloom_far": ((bloom_far.width(), bloom_far.height()),
                          signature(bloom_far)) if bloom_far else None,
            "final": ((final.width(), final.height()), signature(final)) if final else None,
        }
        outputs = [report[str(case)] for case in cases]
        if len(set(outputs)) < 4 or any(not value for value in outputs):
            failures.append({"signatures": outputs})
        if (not state["hdr_valid"] or state["hdr_frames"] < len(cases)
                or state["hdr_passes"] < len(cases)
                or state["bloom_passes"] < state["bloom_levels"]
                or len(state["bloom_sizes"]) != state["bloom_levels"]
                or not state["auto_exposure"] or state["auto_updates"] < 2
                or abs(state["auto_current"] - 1.0) < 0.001
                or state["error"] or report["attachments"]["scene"] is None
                or report["attachments"]["bloom_near"] is None
                or report["attachments"]["bloom_far"] is None
                or report["attachments"]["final"] is None
                or report["attachments"]["scene"][1] == report["attachments"]["final"][1]):
            failures.append({"state": state, "attachments": report["attachments"]})
        if (viewport.upload_count != report["upload"]
                or window.canvas.render_revision != report["revision"]
                or window.canvas.history_manager.current_index != report["history"]):
            failures.append({"neutrality": (
                viewport.upload_count, window.canvas.render_revision,
                window.canvas.history_manager.current_index)})
        print(json.dumps({"report": report, "failures": failures},
                         ensure_ascii=False, indent=2))
        lab.hide(); window.close(); app.exit(1 if failures else 0)

    QTimer.singleShot(700, begin)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
