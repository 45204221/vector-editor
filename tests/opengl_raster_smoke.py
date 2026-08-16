"""Short real-window smoke test for M13; not part of unittest discovery."""

import json
import os
import sys


os.environ.setdefault("QT_OPENGL", "desktop")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtCore import QTimer
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
    window.resize(760, 520)
    window.canvas.show_grid = False
    first = window.canvas.create_rectangle(80, 70, 260, 190)
    first.fill_color = QColor(30, 150, 240, 180)
    second = window.canvas.create_ellipse(210, 130, 300, 210)
    second.fill_color = QColor(255, 80, 90, 170)
    window.canvas.add_shape(first)
    window.canvas.add_shape(second)
    window.show()
    window.graphics_view.set_render_backend("opengl")

    cases = [
        ("vertex_color", "alpha", "none"),
        ("screen_gradient", "alpha", "none"),
        ("time_pulse", "alpha", "none"),
        ("coverage", "alpha", "none"),
        ("screen_gradient", "additive", "none"),
        ("screen_gradient", "opaque", "none"),
        ("screen_gradient", "alpha", "scissor"),
        ("screen_gradient", "alpha", "stencil"),
    ]
    results = []
    current = {"case": None}

    def record():
        if current["case"] is None:
            return
        backend = window.graphics_view.render_item.backend
        state = backend.experiment_state()
        results.append({
            "case": current["case"],
            "state": state,
            "fallback": backend.fallback_active,
            "error": backend.last_error,
            "vertices": backend.last_gpu_vertices,
            "batches": backend.last_gpu_batches,
            "pulse_timer": window.graphics_view.shader_timer.isActive(),
        })

    def step(index=0):
        record()
        if index >= len(cases):
            failures = [item for item in results
                        if item["fallback"] or item["error"] or
                        item["vertices"] <= 0 or item["batches"] <= 0]
            stencil = next(item for item in results if item["case"][2] == "stencil")
            bits = stencil["state"]["stencil_bits"]
            expected_clip = "stencil" if bits > 0 else "scissor"
            if stencil["state"]["effective_clip_mode"] != expected_clip:
                failures.append(stencil)
            pulse = next(item for item in results if item["case"][0] == "time_pulse")
            if not pulse["pulse_timer"] or pulse["state"]["time_uniform"] <= 0.0:
                failures.append(pulse)
            print(json.dumps({"results": results, "failures": failures},
                             ensure_ascii=False, indent=2))
            window.close()
            app.exit(1 if failures else 0)
            return
        current["case"] = cases[index]
        window.graphics_view.set_raster_experiment(*cases[index])
        window.graphics_view.scene.update()
        QTimer.singleShot(120, lambda: step(index + 1))

    QTimer.singleShot(250, step)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
