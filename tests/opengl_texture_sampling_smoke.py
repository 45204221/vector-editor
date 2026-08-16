"""Real-window smoke test for the M19 texture sampling laboratory."""

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
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication
from ui.main_window import MainWindow


def signature(image):
    converted = image.convertToFormat(QImage.Format_RGBA8888)
    pointer = converted.bits(); pointer.setsize(converted.byteCount())
    payload = bytes(pointer)
    return {"size": (converted.width(), converted.height()),
            "sha1": hashlib.sha1(payload).hexdigest()[:16],
            "bytes": len(payload)}


def main():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(); window.resize(1000, 700); window.show()
    window.show_texture_sampling_panel()
    lab = window.engine_lab_window; lab.resize(1200, 760)
    panel, failures, report = window.texture_sampling_panel, [], {}
    revision = window.canvas.render_revision
    history = window.canvas.history_manager.current_index
    cases = (("nearest", "final", False, 0),
             ("bilinear", "final", False, 0),
             ("trilinear", "final", False, 0),
             ("trilinear", "mip_color", False, 0),
             ("trilinear", "lod_heatmap", False, 0),
             ("trilinear", "final", True, 0),
             ("trilinear", "final", True, 7))

    def run_case(index=0):
        if index >= len(cases):
            before_phase = panel.phase
            before_uploads = panel.viewport.texture_uploads
            panel.animate_check.setChecked(True)
            QTimer.singleShot(260, lambda: finish(before_phase, before_uploads))
            return
        filter_mode, view_mode, manual, level = cases[index]
        panel.filter_combo.setCurrentIndex(panel.filter_combo.findData(filter_mode))
        panel.view_combo.setCurrentIndex(panel.view_combo.findData(view_mode))
        panel.manual_lod_check.setChecked(manual)
        panel.lod_slider.setValue(level)
        panel.viewport.update()
        QTimer.singleShot(180, lambda: capture(index, filter_mode, view_mode,
                                               manual, level))

    def capture(index, filter_mode, view_mode, manual, level):
        key = f"{filter_mode}:{view_mode}:manual={manual}:L{level}"
        report[key] = signature(panel.viewport.grabFramebuffer())
        run_case(index + 1)

    def finish(before_phase, before_uploads):
        panel.animate_check.setChecked(False)
        state = panel.viewport.runtime_state(); report["state"] = state
        report["animation"] = {
            "phase_before": before_phase, "phase_after": panel.phase,
            "uploads_before": before_uploads,
            "uploads_after": panel.viewport.texture_uploads}
        hashes = {key: value["sha1"] for key, value in report.items()
                  if isinstance(value, dict) and "sha1" in value}
        required = (state["context_valid"] and state["texture_valid"] and
                    not state["error"] and state["texture_uploads"] == 1 and
                    state["geometry_uploads"] == 1 and
                    len(set(hashes.values())) >= 5 and
                    panel.phase != before_phase and
                    panel.viewport.texture_uploads == before_uploads and
                    window.canvas.render_revision == revision and
                    window.canvas.history_manager.current_index == history)
        if not required:
            failures.append({"state": state, "hashes": hashes,
                             "animation": report["animation"]})
        print(json.dumps({"report": report, "failures": failures}, indent=2))
        lab.hide(); window.close(); app.exit(1 if failures else 0)

    QTimer.singleShot(900, run_case)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
