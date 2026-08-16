"""Short real-context smoke test for M14.2 two-pass GPU postprocessing."""

import json
import os
import sys
import tempfile


os.environ.setdefault("QT_OPENGL", "desktop")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QColor, QImage, QSurfaceFormat
from PyQt5.QtWidgets import QApplication

from ui.main_window import MainWindow


def image_signature(image):
    totals = [0, 0, 0, 0]
    non_white = 0
    samples = 0
    step_x = max(1, image.width() // 80)
    step_y = max(1, image.height() // 80)
    for y in range(0, image.height(), step_y):
        for x in range(0, image.width(), step_x):
            color = image.pixelColor(x, y)
            values = (color.red(), color.green(), color.blue(), color.alpha())
            for index, value in enumerate(values):
                totals[index] += value
            non_white += int(values[:3] != (255, 255, 255))
            samples += 1
    return tuple(totals), non_white, samples


def is_grayscale(image):
    step_x = max(1, image.width() // 80)
    step_y = max(1, image.height() // 80)
    for y in range(0, image.height(), step_y):
        for x in range(0, image.width(), step_x):
            color = image.pixelColor(x, y)
            if color.red() != color.green() or color.green() != color.blue():
                return False
    return True


def main():
    surface_format = QSurfaceFormat.defaultFormat()
    surface_format.setSamples(max(4, surface_format.samples()))
    surface_format.setStencilBufferSize(max(8, surface_format.stencilBufferSize()))
    QSurfaceFormat.setDefaultFormat(surface_format)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(900, 650)
    window.canvas.show_grid = False
    first = window.canvas.create_rectangle(150, 160, 950, 620)
    first.style.brush_color = "#1482F5"
    first.style.opacity = 0.82
    second = window.canvas.create_ellipse(650, 430, 850, 650)
    second.style.brush_color = "#F5465F"
    second.style.opacity = 0.75
    window.canvas.add_shape(first)
    window.canvas.add_shape(second)
    window.show()
    view = window.graphics_view
    view.set_render_backend("opengl")
    app.processEvents()
    view.fit_to_window()
    view.set_picking_mode("compare")
    window.show_pipeline_panel()
    window.pipeline_panel.tabs.setCurrentIndex(4)

    def verify():
        backend = view.render_item.backend
        viewport = view.viewport()
        images = {}
        failures = []
        viewport.makeCurrent()
        try:
            source = backend.render_offscreen_attachment("none", 1, "color")
            for effect in ("none", "grayscale", "invert", "edge"):
                images[effect] = backend.render_offscreen_attachment(
                    effect, 1, "postprocess")
            double = backend.render_offscreen_attachment(
                "grayscale", 2, "postprocess")
            identifier = backend.render_offscreen_attachment("none", 1, "id")
        finally:
            viewport.doneCurrent()

        all_images = [source, *images.values(), double, identifier]
        if any(image is None or image.isNull() for image in all_images):
            failures.append({"null_image": True, "error": backend.last_offscreen_error})
        else:
            base_size = (source.width(), source.height())
            if any((image.width(), image.height()) != base_size
                   for image in images.values()):
                failures.append({"one_x_size": base_size})
            if (double.width(), double.height()) != (base_size[0] * 2, base_size[1] * 2):
                failures.append({"double_size": (double.width(), double.height())})
            signatures = {name: image_signature(image) for name, image in images.items()}
            if len(set(signatures.values())) != 4:
                failures.append({"signatures_not_unique": signatures})
            if image_signature(source)[1] == 0:
                failures.append({"source_has_no_vector_pixels": image_signature(source)})
            if not is_grayscale(images["grayscale"]):
                failures.append({"grayscale_channels": False})

            handle, path = tempfile.mkstemp(suffix=".png")
            os.close(handle)
            try:
                saved = double.save(path, "PNG")
                loaded = QImage(path)
                if not saved or loaded.isNull() or loaded.size() != double.size():
                    failures.append({"png_export": False})
            finally:
                os.remove(path)

        state = backend.offscreen_state()
        lab = window.engine_lab_window
        if not lab.isVisible() or lab.pages.currentIndex() != 0:
            failures.append({"engine_lab_page": lab.pages.currentIndex()})
        lab.close()
        if lab.isVisible():
            failures.append({"engine_lab_close_did_not_hide": True})
        window.show_pipeline_panel()
        if not lab.isVisible() or window.pipeline_panel.tabs.currentIndex() != 4:
            failures.append({"engine_lab_reopen_state": False})
        if (backend.fallback_active or backend.last_error or backend.last_offscreen_error
                or not state["color_target_valid"] or not state["post_target_valid"]):
            failures.append({
                "fallback": backend.fallback_active, "error": backend.last_error,
                "offscreen_error": backend.last_offscreen_error, "state": state,
            })
        print(json.dumps({
            "one_x": (source.width(), source.height()) if source else (0, 0),
            "two_x": (double.width(), double.height()) if double else (0, 0),
            "signatures": ({name: image_signature(image) for name, image in images.items()}
                           if all(image is not None and not image.isNull()
                                  for image in images.values()) else {}),
            "state": state, "failures": failures,
        }, ensure_ascii=False, indent=2))
        window.close()
        app.exit(1 if failures else 0)

    QTimer.singleShot(700, verify)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
