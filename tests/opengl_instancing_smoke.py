"""Real-context smoke test for M15.1 texture atlases and GPU instancing."""

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


def main():
    surface_format = QSurfaceFormat.defaultFormat()
    surface_format.setSamples(max(4, surface_format.samples()))
    surface_format.setStencilBufferSize(max(8, surface_format.stencilBufferSize()))
    QSurfaceFormat.setDefaultFormat(surface_format)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(960, 680)
    window.canvas.show_grid = False
    shape = window.canvas.create_rectangle(120, 100, 420, 280)
    shape.style.brush_color = "#246FC7"
    window.canvas.add_shape(shape)
    window.show()

    view = window.graphics_view
    view.set_render_backend("opengl")
    view.fit_to_window()
    window.show_instancing_panel()
    view.set_instancing_experiment(
        enabled=True, count=500, sprite_mode="mixed", animate=True, seed=1337)

    results = {}
    failures = []

    def check_initial():
        state = view.instancing_experiment_state()
        results["initial"] = dict(state)
        if (not state["resources_valid"] or state["count"] != 500
                or state["instance_bytes"] != 500 * 56
                or state["draw_calls"] != 1 or state["upload_count"] != 1
                or state["time_uniform"] <= 0 or state["error"]
                or not view.sprite_timer.isActive()):
            failures.append({"initial": state,
                             "timer": view.sprite_timer.isActive()})
        QTimer.singleShot(250, check_animation)

    def check_animation():
        state = view.instancing_experiment_state()
        results["animation"] = dict(state)
        initial = results["initial"]
        if (state["upload_count"] != initial["upload_count"]
                or state["time_uniform"] <= initial["time_uniform"]
                or state["draw_calls"] != 1):
            failures.append({"animation": state})
        view.set_instancing_experiment(animate=False)
        QTimer.singleShot(180, check_static)

    def check_static():
        state = view.instancing_experiment_state()
        results["static"] = dict(state)
        if view.sprite_timer.isActive() or state["upload_count"] != 1:
            failures.append({"static": state,
                             "timer": view.sprite_timer.isActive()})
        view.set_instancing_experiment(count=10000, sprite_mode="star")
        QTimer.singleShot(260, check_large)

    def check_large():
        state = view.instancing_experiment_state()
        results["large"] = dict(state)
        if (state["count"] != 10000 or state["instance_bytes"] != 560000
                or state["draw_calls"] != 1 or state["upload_count"] != 2
                or state["error"]):
            failures.append({"large": state})
        view.set_render_backend("command")
        results["command_timer"] = view.sprite_timer.isActive()
        preserved = view.instancing_experiment_state()
        if view.sprite_timer.isActive() or preserved["count"] != 10000:
            failures.append({"command": preserved,
                             "timer": view.sprite_timer.isActive()})
        view.set_render_backend("opengl")
        QTimer.singleShot(500, check_rebuilt)

    def check_rebuilt():
        backend = view.render_item.backend
        state = view.instancing_experiment_state()
        results["rebuilt"] = dict(state)
        lab = window.engine_lab_window
        if (not state["resources_valid"] or state["count"] != 10000
                or state["instance_bytes"] != 560000
                or state["draw_calls"] != 1 or state["upload_count"] != 1
                or state["error"] or backend.fallback_active
                or backend.last_error):
            failures.append({"rebuilt": state,
                             "fallback": backend.fallback_active,
                             "backend_error": backend.last_error})
        if not lab.isVisible() or lab.pages.currentIndex() != 2:
            failures.append({"engine_lab_page": lab.pages.currentIndex(),
                             "visible": lab.isVisible()})
        print(json.dumps({"results": results, "failures": failures},
                         ensure_ascii=False, indent=2))
        window.close()
        app.exit(1 if failures else 0)

    QTimer.singleShot(700, check_initial)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
