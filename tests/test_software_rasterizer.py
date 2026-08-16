import os
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from core.mesh3d import cube_mesh
from core.pipeline3d import Pipeline3DConfig
from core.software_pipeline import raster_input_vertices
from core.software_rasterizer import software_rasterize
from core.raster_comparison import compare_rgba, pixel_probe
from core import native_rasterizer
from PyQt5.QtWidgets import QApplication
from ui.main_window import MainWindow


APP = QApplication.instance() or QApplication([])


def triangle(z=0.0, scale_w=(1.0, 1.0, 1.0)):
    ndc = ((-0.8, -0.8), (0.8, -0.8), (0.0, 0.8))
    colors = ((0.2, 0.5, 1.0), (0.8, 0.2, 0.3), (0.4, 1.0, 0.1))
    return tuple((point[0] * w, point[1] * w, z * w, w, *color)
                 for point, color, w in zip(ndc, colors, scale_w))


class SoftwareRasterizerTests(unittest.TestCase):
    def test_single_triangle_outputs_three_rgba_attachments(self):
        result = software_rasterize(triangle(), 64, 48)
        self.assertEqual(result.input_triangles, 1)
        self.assertEqual(result.clipped_triangles, 1)
        self.assertEqual(result.sample_count, 1)
        self.assertEqual(result.rasterized_triangles, 1)
        self.assertGreater(result.covered_fragments, 500)
        self.assertEqual(result.covered_fragments, result.depth_passed_fragments)
        self.assertEqual(len(result.color), 64 * 48 * 4)
        self.assertEqual(len(result.barycentric), 64 * 48 * 4)
        self.assertEqual(len(result.depth), 64 * 48 * 4)
        self.assertEqual(len(result.primitive_id), 64 * 48 * 4)
        self.assertNotEqual(result.color, result.barycentric)

    def test_homogeneous_clip_splits_crossing_triangle_and_rejects_outside(self):
        crossing = ((-0.6, -0.6, 0.0, 1.0, 1.0, 0.0, 0.0),
                    (1.7, -0.4, 0.0, 1.0, 0.0, 1.0, 0.0),
                    (0.0, 0.8, 0.0, 1.0, 0.0, 0.0, 1.0))
        clipped = software_rasterize(crossing, 64, 64, clip_volume=True)
        unclipped = software_rasterize(crossing, 64, 64, clip_volume=False)
        self.assertEqual(clipped.clipped_triangles, 2)
        self.assertEqual(unclipped.clipped_triangles, 1)
        self.assertGreater(clipped.resolved_covered_pixels, 0)
        outside = tuple((x + 4.0, y, z, w, r, g, b)
                        for x, y, z, w, r, g, b in triangle())
        self.assertEqual(software_rasterize(
            outside, 32, 32, clip_volume=True).rasterized_triangles, 0)

    def test_top_left_rule_assigns_shared_edge_once(self):
        red = (1.0, 0.0, 0.0)
        green = (0.0, 1.0, 0.0)
        points = ((-0.8, -0.8), (0.8, -0.8), (0.8, 0.8), (-0.8, 0.8))
        vertices = tuple((points[index][0], points[index][1], 0.0, 1.0,
                          *(red if triangle_index == 0 else green))
                         for triangle_index, indices in enumerate(((0, 1, 2), (0, 2, 3)))
                         for index in indices)
        result = software_rasterize(vertices, 64, 64)
        self.assertEqual(result.covered_fragments, result.depth_passed_fragments)
        self.assertEqual(result.covered_fragments, result.resolved_covered_pixels)

    def test_four_sample_msaa_resolves_partial_edge_coverage(self):
        single = software_rasterize(triangle(), 48, 48, sample_count=1)
        multisample = software_rasterize(triangle(), 48, 48, sample_count=4)
        self.assertEqual(multisample.sample_count, 4)
        self.assertNotEqual(multisample.color, single.color)
        self.assertGreater(multisample.covered_fragments,
                           single.covered_fragments * 3)
        self.assertGreaterEqual(multisample.resolved_covered_pixels,
                                single.resolved_covered_pixels)

    def test_depth_buffer_keeps_nearest_triangle(self):
        far = tuple((*vertex[:2], 0.7, *vertex[3:4], 0, 0, 1)
                    for vertex in triangle())
        near = tuple((*vertex[:2], -0.5, *vertex[3:4], 1, 0, 0)
                     for vertex in triangle())
        result = software_rasterize(near + far, 32, 32)
        center = (16 * 32 + 16) * 4
        self.assertGreater(result.color[center], result.color[center + 2])
        primitive = (result.primitive_id[center] |
                     result.primitive_id[center + 1] << 8 |
                     result.primitive_id[center + 2] << 16)
        self.assertEqual(primitive, 1)
        self.assertGreater(result.covered_fragments,
                           result.depth_passed_fragments)

    def test_perspective_correct_changes_interpolated_attributes(self):
        vertices = triangle(scale_w=(0.7, 2.2, 1.3))
        linear = software_rasterize(vertices, 64, 64, False)
        corrected = software_rasterize(vertices, 64, 64, True)
        self.assertNotEqual(linear.barycentric, corrected.barycentric)
        self.assertNotEqual(linear.color, corrected.color)
        self.assertEqual(linear.depth, corrected.depth)

    def test_culling_and_behind_camera_skip(self):
        reversed_triangle = tuple(reversed(triangle()))
        self.assertEqual(software_rasterize(
            reversed_triangle, 32, 32, cull_back_faces=True).rasterized_triangles, 0)
        self.assertEqual(software_rasterize(
            reversed_triangle, 32, 32, cull_back_faces=False).rasterized_triangles, 1)
        behind = tuple((*vertex[:3], -1.0, *vertex[4:]) for vertex in triangle())
        self.assertEqual(software_rasterize(
            behind, 32, 32, cull_back_faces=False).rasterized_triangles, 0)

    def test_shared_pipeline_builds_object_and_receiver_clip_vertices(self):
        mesh = cube_mesh()
        vertices = raster_input_vertices(mesh.vertices, Pipeline3DConfig(), 256, 256)
        self.assertEqual(len(vertices), mesh.vertex_count + 6)
        self.assertTrue(all(len(vertex) == 7 for vertex in vertices))
        self.assertTrue(all(0.0 <= channel <= 1.0
                            for vertex in vertices for channel in vertex[4:]))

    @unittest.skipUnless(native_rasterizer.is_available(),
                         "native rasterizer module not built")
    def test_cpp_matches_python_reference(self):
        vertices = list(triangle(scale_w=(0.8, 1.7, 1.2)))
        vertices[1] = (2.0, *vertices[1][1:])
        for samples in (1, 4):
            reference = software_rasterize(
                vertices, 48, 40, True, True, True, samples)
            actual = native_rasterizer.software_rasterize(
                vertices, 48, 40, True, True, True, samples)
            self.assertEqual(actual.backend, "C++ native")
            self.assertEqual(actual.color, reference.color)
            self.assertEqual(actual.barycentric, reference.barycentric)
            self.assertEqual(actual.depth, reference.depth)
            self.assertEqual(actual.primitive_id, reference.primitive_id)
            self.assertEqual(actual.clipped_triangles,
                             reference.clipped_triangles)
            self.assertEqual(actual.rasterized_triangles,
                             reference.rasterized_triangles)
            self.assertEqual(actual.covered_fragments,
                             reference.covered_fragments)
            self.assertEqual(actual.depth_passed_fragments,
                             reference.depth_passed_fragments)
            self.assertEqual(actual.resolved_covered_pixels,
                             reference.resolved_covered_pixels)


class SoftwareRasterizerIntegrationTests(unittest.TestCase):
    def test_cpu_gpu_page_is_history_neutral(self):
        window = MainWindow(); panel = window.pipeline3d_panel
        revision = window.canvas.render_revision
        history = window.canvas.history_manager.current_index
        panel.software_resolution_combo.setCurrentIndex(
            panel.software_resolution_combo.findData(128))
        panel._run_software_rasterizer(); APP.processEvents()
        result = panel.software_result
        self.assertIsNotNone(result)
        self.assertEqual((result.width, result.height), (128, 128))
        self.assertGreater(result.depth_passed_fragments, 0)
        self.assertFalse(panel.software_stale)
        self.assertEqual(window.canvas.render_revision, revision)
        self.assertEqual(window.canvas.history_manager.current_index, history)
        panel.software_attachment_combo.setCurrentIndex(
            panel.software_attachment_combo.findData("barycentric"))
        self.assertFalse(panel.software_preview.pixmap().isNull())
        panel.software_probe_x.setMaximum(511); panel.software_probe_y.setMaximum(511)
        panel.software_probe_x.setValue(500); panel.software_probe_y.setValue(500)
        panel.software_gpu_buffer = result.color
        # Simulate a descending-resolution transition where one axis updates first.
        panel.software_probe_x.setMaximum(127)
        panel._update_software_probe()
        self.assertIn("Pixel", panel.software_probe_label.text())
        window.close()

    def test_aligned_metrics_heatmap_and_probe(self):
        result = software_rasterize(triangle(), 32, 32)
        identical = compare_rgba(result.color, result.color, 32, 32)
        self.assertEqual(identical.coverage_mismatch, 0)
        self.assertEqual(identical.coverage_iou, 1.0)
        self.assertEqual(identical.mae, 0.0)
        changed = bytearray(result.color)
        center = (16 * 32 + 16) * 4
        changed[center] = min(255, changed[center] + 40)
        comparison = compare_rgba(result.color, bytes(changed), 32, 32)
        self.assertGreater(comparison.mae, 0.0)
        self.assertEqual(comparison.max_error, 40)
        self.assertEqual(len(comparison.heatmap), 32 * 32 * 4)
        probe = pixel_probe(result, bytes(changed), 16, 16)
        self.assertIsNotNone(probe["triangle_id"])
        self.assertGreater(probe["absolute_rgb"][0], 0)
        self.assertAlmostEqual(sum(probe["barycentric"]), 1.0, places=2)


if __name__ == "__main__":
    unittest.main()
