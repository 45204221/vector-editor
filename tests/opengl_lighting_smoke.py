"""Short real-context smoke test for M16.2 three-pass OpenGL lighting."""

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


def luminance_stats(image, step=4):
    values = []
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            color = image.pixelColor(x, y)
            values.append((color.red() + color.green() + color.blue()) / 3.0)
    return min(values), max(values), sum(values) / len(values)


def color_regions(image, step=3):
    red, blue = 0, 0
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            color = image.pixelColor(x, y)
            if color.red() > color.blue() + 35 and color.red() > color.green() + 20:
                red += 1
            if color.blue() > color.red() + 35 and color.blue() > color.green() + 10:
                blue += 1
    return red, blue


def desktop_view_image(app, view):
    viewport = view.viewport()
    point = viewport.mapToGlobal(viewport.rect().topLeft())
    return app.primaryScreen().grabWindow(
        0, point.x(), point.y(), viewport.width(), viewport.height()).toImage()


def main():
    surface = QSurfaceFormat.defaultFormat()
    surface.setStencilBufferSize(max(8, surface.stencilBufferSize()))
    QSurfaceFormat.setDefaultFormat(surface)
    app = QApplication.instance() or QApplication([])
    window = MainWindow(); window.resize(1050, 720)
    window.canvas.show_grid = False
    window.canvas.add_shape(window.canvas.create_rectangle(480, 250, 320, 220))
    window.canvas.add_shape(window.canvas.create_rectangle(1080, 650, 260, 300))
    window.show()
    view = window.graphics_view
    view.fit_to_window(); view.set_render_backend("opengl")
    view.set_lighting_experiment(
        enabled=os.environ.get("LIGHTING_ENABLED", "1") != "0",
        gpu_lighting=os.environ.get("LIGHTING_GPU", "1") != "0",
        debug_mode="final",
        light_x=760, light_y=520, radius=460, intensity=1.15,
        ambient=0.10, color="#FFD36A", use_native=True)
    if os.environ.get("LIGHTING_MULTI", "1") != "0":
        view.add_lighting_source()
        view.set_selected_light_parameters(
            x=430, y=330, radius=330, intensity=1.0, color="#FF4545")
        view.add_lighting_source()
        view.set_selected_light_parameters(
            x=1120, y=700, radius=360, intensity=1.0, color="#458CFF")
    document = window.canvas._capture_document_state()
    history = window.canvas.history_manager.current_index
    report, failures = {}, []

    def mark(stage):
        print(json.dumps({"stage": stage}, ensure_ascii=False), flush=True)

    def initial():
        mark("initial")
        backend = view.render_item.backend
        state = view.lighting_experiment_state()
        mask = view.render_lighting_attachment("mask")
        light = view.render_lighting_attachment("light")
        lit = desktop_view_image(app, view)
        report["initial"] = state
        report["mask_luma"] = luminance_stats(mask) if mask else None
        report["light_luma"] = luminance_stats(light) if light else None
        report["light_color_regions"] = color_regions(light) if light else None
        report["lit_luma"] = luminance_stats(lit)
        if (not state["gpu_active"] or not state["mask_valid"]
                or not state["light_valid"] or state["draw_calls"] != 7
                or state["light_count"] != 3
                or state["fan_vertices"] < 5 or state["fan_vbo_bytes"] <= 0
                or state["error"] or backend.fallback_active or backend.last_error):
            failures.append({"initial_state": state,
                             "backend_error": backend.last_error})
        if not mask or report["mask_luma"][0] > 5 or report["mask_luma"][1] < 245:
            failures.append({"mask_range": report["mask_luma"]})
        if (not light or report["light_luma"][0] > 45
                or report["light_luma"][1] < 180):
            failures.append({"light_range": report["light_luma"]})
        if (not light or min(report["light_color_regions"]) < 10):
            failures.append({"colored_regions": report["light_color_regions"]})
        report["upload_before_zoom"] = state["upload_count"]
        report["builds_before_uniform"] = state["visibility_build_count"]
        view.set_lighting_experiment(gpu_lighting=False)
        QTimer.singleShot(300, unlit)

    def unlit():
        mark("unlit")
        image = desktop_view_image(app, view)
        report["unlit_luma"] = luminance_stats(image)
        if report["lit_luma"][2] >= report["unlit_luma"][2] * 0.94:
            failures.append({"composite_not_darker": (
                report["lit_luma"], report["unlit_luma"])})
        view.set_lighting_experiment(gpu_lighting=True)
        view.zoom_in()
        QTimer.singleShot(300, zoomed)

    def zoomed():
        mark("zoomed")
        state = view.lighting_experiment_state()
        report["after_zoom"] = state
        if state["upload_count"] != report["upload_before_zoom"]:
            failures.append({"zoom_reuploaded": state["upload_count"]})
        view.set_selected_light_parameters(intensity=0.65, radius=420)
        QTimer.singleShot(300, uniform_changed)

    def uniform_changed():
        mark("uniform_changed")
        state = view.lighting_experiment_state()
        report["after_uniform"] = state
        if (state["upload_count"] != report["upload_before_zoom"]
                or state["visibility_build_count"] != report["builds_before_uniform"]):
            failures.append({"uniform_invalidated_geometry": state})
        view.set_selected_light_parameters(x=1000, y=610)
        QTimer.singleShot(300, moved)

    def moved():
        mark("moved")
        state = view.lighting_experiment_state()
        report["after_move"] = state
        if state["upload_count"] <= report["upload_before_zoom"]:
            failures.append({"move_not_uploaded": state["upload_count"]})
        view.set_render_backend("command")
        view.set_render_backend("opengl")
        QTimer.singleShot(450, restored)

    def restored():
        mark("restored")
        backend = view.render_item.backend
        state = view.lighting_experiment_state()
        report["restored"] = state
        if (not state["gpu_active"] or state["draw_calls"] != 7
                or state["light_count"] != 3
                or state["error"] or backend.fallback_active or backend.last_error):
            failures.append({"restore": state, "backend_error": backend.last_error})
        if (window.canvas._capture_document_state() != document
                or window.canvas.history_manager.current_index != history):
            failures.append({"document_mutated": True})
        print(json.dumps({"report": report, "failures": failures},
                         ensure_ascii=False, indent=2))
        window.close(); app.exit(1 if failures else 0)

    QTimer.singleShot(600, initial)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
