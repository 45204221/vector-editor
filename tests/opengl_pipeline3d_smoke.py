"""Real-context smoke test for the independent M17.1 3D pipeline viewport."""

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


def image_signature(image, step=4):
    red = green = blue = count = non_background = 0
    bins = set()
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            color = image.pixelColor(x, y)
            red += color.red(); green += color.green(); blue += color.blue(); count += 1
            bins.add((color.red() // 24, color.green() // 24, color.blue() // 24))
            if color.red() > 30 or color.green() > 35 or color.blue() > 45:
                non_background += 1
    return (round(red / count, 2), round(green / count, 2),
            round(blue / count, 2), len(bins), non_background)


def main():
    surface = QSurfaceFormat.defaultFormat()
    surface.setDepthBufferSize(max(24, surface.depthBufferSize()))
    surface.setStencilBufferSize(max(8, surface.stencilBufferSize()))
    QSurfaceFormat.setDefaultFormat(surface)
    app = QApplication.instance() or QApplication([])
    window = MainWindow(); window.resize(900, 650); window.show()
    window.show_pipeline3d_panel()
    lab = window.engine_lab_window; lab.resize(1050, 760)
    panel = window.pipeline3d_panel; viewport = panel.viewport
    report, failures, signatures = {}, [], {}

    def capture_mode(modes, index=0):
        if index >= len(modes):
            select_shape(); return
        mode = modes[index]
        panel.mode_combo.setCurrentIndex(panel.mode_combo.findData(mode))

        def record():
            image = viewport.grabFramebuffer()
            signatures[mode] = image_signature(image)
            capture_mode(modes, index + 1)
        QTimer.singleShot(220, record)

    def initial():
        state = viewport.runtime_state()
        report["initial"] = state
        report["mesh_backend"] = viewport.mesh.backend
        if (not state["context_valid"] or state["vertices"] != 36
                or state["triangles"] != 12 or state["draw_calls"] != 4
                or state["upload_count"] != 1 or state["error"]
                or viewport.mesh.backend != "C++ native"):
            failures.append({"initial": report["initial"],
                             "backend": viewport.mesh.backend})
        capture_mode(("final", "normals", "depth", "shadow_map", "wireframe"))

    def select_shape():
        report["signatures"] = signatures
        if (len(set(signatures.values())) < 3
                or any(value[4] < 20 for value in signatures.values())):
            failures.append({"view_modes": signatures})
        shape = window.canvas.create_ellipse(120, 100, 240, 160)
        window.canvas.add_shape(shape); window.canvas.select_shape(shape)
        panel.source_combo.setCurrentIndex(panel.source_combo.findData("selection"))
        report["shape_id"] = shape.id
        QTimer.singleShot(350, selected)

    def selected():
        state = viewport.runtime_state()
        report["selected"] = state
        report["source_shape"] = panel.source_shape_id
        report["selected_backend"] = viewport.mesh.backend
        if (panel.source_shape_id != report["shape_id"]
                or state["vertices"] <= 36 or state["upload_count"] != 2
                or state["error"] or viewport.mesh.backend != "C++ native"):
            failures.append({"selected": state, "source": panel.source_shape_id})
        panel.mode_combo.setCurrentIndex(panel.mode_combo.findData("final"))
        QTimer.singleShot(220, selected_final)

    def selected_final():
        state = viewport.runtime_state()
        attachment_signatures = {}
        for kind in ("normal", "depth", "shadow"):
            image = viewport.render_attachment(kind)
            attachment_signatures[kind] = (image.width(), image.height(),
                                            image_signature(image)) if image else None
        report["attachments"] = attachment_signatures
        if (any(value is None for value in attachment_signatures.values())
                or len({value[2] for value in attachment_signatures.values()}) < 3
                or attachment_signatures["shadow"][:2] != (512, 512)):
            failures.append({"attachments": attachment_signatures})
        report["lighting_before"] = image_signature(viewport.grabFramebuffer())
        upload = state["upload_count"]
        revision = window.canvas.render_revision
        history = window.canvas.history_manager.current_index
        report["before_uniform"] = (upload, revision, history)
        panel.light_x_spin.setValue(-3.5)
        panel.pcf_combo.setCurrentIndex(panel.pcf_combo.findData(2))
        QTimer.singleShot(260, lighting_changed)

    def lighting_changed():
        report["lighting_after"] = image_signature(viewport.grabFramebuffer())
        if report["lighting_after"] == report["lighting_before"]:
            failures.append({"lighting_signatures": (report["lighting_before"],
                                                      report["lighting_after"])})
        panel.render_path_combo.setCurrentIndex(
            panel.render_path_combo.findData("deferred"))
        panel.light_count_combo.setCurrentIndex(
            panel.light_count_combo.findData(8))
        QTimer.singleShot(320, deferred_eight)

    def deferred_eight():
        state = viewport.runtime_state()
        report["deferred_eight_state"] = state
        report["deferred_eight"] = image_signature(viewport.grabFramebuffer())
        gbuffer = {}
        for kind in ("g_position", "g_normal", "g_albedo"):
            image = viewport.render_attachment(kind)
            gbuffer[kind] = (image.width(), image.height(),
                             image_signature(image)) if image else None
        report["gbuffer"] = gbuffer
        if (state["draw_calls"] != 5 or state["gbuffer_passes"] < 1
                or state["lighting_passes"] < 1 or state["error"]
                or any(value is None for value in gbuffer.values())
                or len({value[2] for value in gbuffer.values()}) < 3):
            failures.append({"deferred": state, "gbuffer": gbuffer})
        panel.light_count_combo.setCurrentIndex(
            panel.light_count_combo.findData(1))
        QTimer.singleShot(280, deferred_one)

    def deferred_one():
        report["deferred_one"] = image_signature(viewport.grabFramebuffer())
        if (report["deferred_one"] == report["deferred_eight"]
                or report["deferred_one"][4] < 20):
            failures.append({"deferred_lights": (report["deferred_one"],
                                                  report["deferred_eight"])})
        panel.ry_spin.setValue(83); panel.fov_spin.setValue(62)
        panel.mode_combo.setCurrentIndex(panel.mode_combo.findData("normals"))
        QTimer.singleShot(300, uniform_changed)

    def uniform_changed():
        state = viewport.runtime_state()
        upload, revision, history = report["before_uniform"]
        report["uniform_changed"] = state
        if (state["upload_count"] != upload or window.canvas.render_revision != revision
                or window.canvas.history_manager.current_index != history
                or state["error"]):
            failures.append({"uniform_changed": state})
        panel.shadow_check.setChecked(False)
        QTimer.singleShot(240, shadow_disabled)

    def shadow_disabled():
        state = viewport.runtime_state()
        report["shadow_disabled"] = state
        upload, revision, history = report["before_uniform"]
        if (state["draw_calls"] != 2 or state["upload_count"] != upload
                or window.canvas.render_revision != revision
                or window.canvas.history_manager.current_index != history
                or state["error"]):
            failures.append({"shadow_disabled": state})
        panel.shadow_check.setChecked(True)
        window.graphics_view.set_render_backend("opengl")
        window.graphics_view.set_render_backend("legacy")
        QTimer.singleShot(350, restored)

    def restored():
        state = viewport.runtime_state()
        report["restored"] = state
        if (not state["context_valid"] or state["draw_calls"] != 4
                or state["error"] or panel.source_shape_id != report["shape_id"]):
            failures.append({"restored": state})
        upload = state["upload_count"]
        revision = window.canvas.render_revision
        history = window.canvas.history_manager.current_index
        panel.software_resolution_combo.setCurrentIndex(
            panel.software_resolution_combo.findData(256))
        panel.software_attachment_combo.setCurrentIndex(
            panel.software_attachment_combo.findData("barycentric"))
        panel.software_perspective_check.setChecked(True)
        panel._run_software_rasterizer()
        corrected = panel.software_result
        corrected_barycentric = corrected.barycentric if corrected else b""
        panel.software_perspective_check.setChecked(False)
        panel._run_software_rasterizer()
        linear = panel.software_result
        normal_comparison = panel.software_comparison
        panel.software_compare_combo.setCurrentIndex(
            panel.software_compare_combo.findData("depth"))
        panel._run_software_rasterizer()
        comparison = panel.software_comparison
        panel.software_probe_x.setValue(128); panel.software_probe_y.setValue(128)
        report["software_raster"] = ({
            "backend": linear.backend, "size": (linear.width, linear.height),
            "triangles": (linear.input_triangles, linear.rasterized_triangles),
            "covered": linear.covered_fragments,
            "depth_passed": linear.depth_passed_fragments,
            "elapsed_ms": linear.elapsed_ms,
            "buffer_bytes": linear.buffer_bytes,
            "perspective_difference": corrected_barycentric != linear.barycentric,
            "comparison": ({
                "normal_iou": normal_comparison.coverage_iou,
                "normal_mae": normal_comparison.mae,
                "depth_cpu_covered": comparison.cpu_covered,
                "depth_gpu_covered": comparison.gpu_covered,
                "depth_mismatch": comparison.coverage_mismatch,
                "depth_iou": comparison.coverage_iou,
                "depth_mae": comparison.mae,
                "depth_rmse": comparison.rmse,
                "depth_max_error": comparison.max_error,
            } if comparison and normal_comparison else None),
        } if linear else None)
        if (linear is None or linear.backend != "C++ native"
                or linear.depth_passed_fragments < 20
                or corrected_barycentric == linear.barycentric
                or comparison is None or normal_comparison is None
                or comparison.union < 20 or comparison.coverage_iou <= 0.5
                or normal_comparison.coverage_iou <= 0.5
                or panel.software_preview.pixmap() is None
                or panel.software_preview.pixmap().isNull()
                or panel.software_gpu_preview.pixmap() is None
                or panel.software_gpu_preview.pixmap().isNull()
                or panel.software_heatmap_preview.pixmap() is None
                or panel.software_heatmap_preview.pixmap().isNull()
                or "Triangle" not in panel.software_probe_label.text()
                or viewport.runtime_state()["upload_count"] != upload
                or window.canvas.render_revision != revision
                or window.canvas.history_manager.current_index != history):
            failures.append({"software_raster": report["software_raster"]})
        print(json.dumps({"report": report, "failures": failures},
                         ensure_ascii=False, indent=2))
        lab.hide(); window.close(); app.exit(1 if failures else 0)

    QTimer.singleShot(700, initial)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
