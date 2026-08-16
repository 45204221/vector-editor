"""Regression for descending M18 CPU/GPU comparison resolutions."""

import json
import os
import sys

os.environ.setdefault("QT_OPENGL", "desktop")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path: sys.path.insert(0, SRC)

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication
from ui.main_window import MainWindow


def main():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(); window.resize(900, 650); window.show()
    window.show_pipeline3d_panel(); panel = window.pipeline3d_panel
    report, failures = [], []

    def run(index=0):
        sequence = ((512, 1), (256, 4), (128, 1),
                    (256, 1), (512, 4), (128, 4))
        if index >= len(sequence):
            print(json.dumps({"report": report, "failures": failures}, indent=2))
            window.engine_lab_window.hide(); window.close()
            app.exit(1 if failures else 0); return
        resolution, samples = sequence[index]
        panel.software_resolution_combo.setCurrentIndex(
            panel.software_resolution_combo.findData(resolution))
        panel.software_samples_combo.setCurrentIndex(
            panel.software_samples_combo.findData(samples))
        panel._run_software_rasterizer()
        result, comparison = panel.software_result, panel.software_comparison
        entry = {"resolution": resolution, "samples": samples,
                 "cpu": (result.width, result.height) if result else None,
                 "gpu": (panel.software_gpu_image.width(),
                         panel.software_gpu_image.height())
                        if panel.software_gpu_image else None,
                 "iou": comparison.coverage_iou if comparison else None,
                 "error": panel.viewport.last_error}
        report.append(entry); print("checkpoint", entry, flush=True)
        if (entry["cpu"] != (resolution, resolution)
                or entry["gpu"] != (resolution, resolution)
                or entry["iou"] is None or entry["error"]):
            failures.append(entry)
        QTimer.singleShot(180, lambda: run(index + 1))

    QTimer.singleShot(700, run)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
