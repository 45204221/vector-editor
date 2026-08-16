import math
import os
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtWidgets import QApplication

from core.canvas import Canvas
from core.mesh3d import MESH_VERTEX_STRIDE, cube_mesh, extrude_mesh
from core.mesh_source import selected_mesh_source
from core import native_mesh
from core.pipeline3d import (ATTACHMENT_MODES, Pipeline3DConfig,
                             blinn_phong_components, light_matrices,
                             scene_lights, trace_pipeline_vertex)
from ui.main_window import MainWindow


APP = QApplication.instance() or QApplication([])


class Mesh3DTests(unittest.TestCase):
    def test_cube_contract_normals_and_payload(self):
        mesh = cube_mesh()
        self.assertEqual(mesh.vertex_count, 36)
        self.assertEqual(mesh.triangle_count, 12)
        self.assertEqual(len(mesh.payload), mesh.vertex_count * MESH_VERTEX_STRIDE)
        for vertex in mesh.vertices:
            self.assertEqual(len(vertex), 6)
            self.assertAlmostEqual(math.sqrt(sum(value * value for value in vertex[3:])),
                                   1.0, places=7)

    def test_rectangle_extrusion_front_back_and_sides(self):
        contour = ((0, 0), (100, 0), (100, 50), (0, 50))
        triangles = (contour[0], contour[1], contour[2],
                     contour[0], contour[2], contour[3])
        mesh = extrude_mesh(contour, triangles, 0.8)
        self.assertEqual(mesh.vertex_count, 36)
        self.assertEqual(sum(1 for vertex in mesh.vertices if vertex[5] == 1.0), 6)
        self.assertEqual(sum(1 for vertex in mesh.vertices if vertex[5] == -1.0), 6)
        self.assertEqual(sum(1 for vertex in mesh.vertices if vertex[5] == 0.0), 24)
        self.assertAlmostEqual(max(vertex[2] for vertex in mesh.vertices), 0.4)
        self.assertAlmostEqual(min(vertex[2] for vertex in mesh.vertices), -0.4)

    @unittest.skipUnless(native_mesh.is_available(), "native mesh module not built")
    def test_cpp_matches_python_mesh(self):
        contour = ((0, 0), (90, 0), (90, 60), (0, 60))
        triangles = (contour[0], contour[1], contour[2],
                     contour[0], contour[2], contour[3])
        reference = extrude_mesh(contour, triangles, 1.1)
        actual = native_mesh.extrude_mesh(contour, triangles, 1.1)
        self.assertEqual(actual.backend, "C++ native")
        self.assertEqual(len(actual.vertices), len(reference.vertices))
        for cpp, python in zip(actual.vertices, reference.vertices):
            for first, second in zip(cpp, python):
                self.assertAlmostEqual(first, second, places=8)

    def test_selected_shape_geometry_source(self):
        canvas = Canvas(400, 300)
        shape = canvas.create_rectangle(40, 50, 120, 80)
        canvas.add_shape(shape); canvas.select_shape(shape)
        source = selected_mesh_source(canvas)
        self.assertTrue(source.valid)
        self.assertEqual(source.shape_id, shape.id)
        self.assertEqual(len(source.contour), 4)
        self.assertEqual(len(source.triangles), 6)
        canvas.clear_selection()
        self.assertFalse(selected_mesh_source(canvas).valid)

    def test_pipeline_trace_has_six_stages_and_clip_test(self):
        config = Pipeline3DConfig(rotation_x=0, rotation_y=0, rotation_z=0,
                                  camera_yaw=0, camera_pitch=0)
        trace = trace_pipeline_vertex((0, 0, 0, 0, 0, 1), config, 800, 600)
        for stage in ("object", "world", "view", "clip", "ndc", "screen"):
            self.assertEqual(len(trace[stage]), 4)
        self.assertTrue(trace["inside_clip"])
        self.assertAlmostEqual(trace["screen"][0], 400.0, places=4)
        self.assertAlmostEqual(trace["screen"][1], 300.0, places=4)

    def test_blinn_phong_reference_and_light_matrix(self):
        config = Pipeline3DConfig(light_x=0, light_y=0, light_z=3,
                                  camera_yaw=0, camera_pitch=0,
                                  ambient=0.2, diffuse=0.7,
                                  specular=0.5, shininess=32)
        terms = blinn_phong_components((0, 0, 1), (0, 0, 0), config)
        self.assertAlmostEqual(terms["ambient"], 0.2)
        self.assertAlmostEqual(terms["diffuse"], 0.7)
        self.assertAlmostEqual(terms["specular"], 0.5)
        light_view, light_projection, light_vp = light_matrices(config)
        self.assertFalse(light_view.isIdentity())
        self.assertFalse(light_projection.isIdentity())
        self.assertFalse(light_vp.isIdentity())

    def test_shadow_configuration_contract(self):
        self.assertEqual({value for _, value in ATTACHMENT_MODES},
                         {"normal", "depth", "shadow", "g_position",
                          "g_normal", "g_albedo"})
        with self.assertRaises(ValueError):
            Pipeline3DConfig(shadow_resolution=128)
        with self.assertRaises(ValueError):
            Pipeline3DConfig(shadow_bias=-0.1)
        with self.assertRaises(ValueError):
            Pipeline3DConfig(pcf_radius=3)
        with self.assertRaises(ValueError):
            Pipeline3DConfig(render_path="clustered")
        with self.assertRaises(ValueError):
            Pipeline3DConfig(light_count=3)
        lights = scene_lights(Pipeline3DConfig(light_count=8))
        self.assertEqual(len(lights), 8)
        self.assertEqual(lights[0][0], (2.8, 4.2, 3.0))
        self.assertEqual(len(set(color for _, color in lights)), 8)


class Pipeline3DIntegrationTests(unittest.TestCase):
    def test_panel_runtime_changes_are_history_neutral(self):
        window = MainWindow()
        panel = window.pipeline3d_panel
        panel.source_combo.setCurrentIndex(panel.source_combo.findData("selection"))
        shape = window.canvas.create_rectangle(20, 30, 100, 70)
        window.canvas.add_shape(shape); window.canvas.select_shape(shape)
        APP.processEvents()
        self.assertEqual(panel.source_shape_id, shape.id)
        self.assertGreater(panel.viewport.mesh.vertex_count, 0)
        runtime_revision = window.canvas.render_revision
        runtime_history = window.canvas.history_manager.current_index
        panel.ry_spin.setValue(65); panel.mode_combo.setCurrentIndex(
            panel.mode_combo.findData("normals"))
        APP.processEvents()
        self.assertEqual(window.canvas.render_revision, runtime_revision)
        self.assertEqual(window.canvas.history_manager.current_index, runtime_history)
        panel.ry_spin.setValue(95); panel.fov_spin.setValue(60)
        panel.light_x_spin.setValue(-2.4)
        panel.specular_spin.setValue(0.9)
        panel.bias_spin.setValue(0.006)
        panel.pcf_combo.setCurrentIndex(panel.pcf_combo.findData(2))
        panel.render_path_combo.setCurrentIndex(
            panel.render_path_combo.findData("deferred"))
        panel.light_count_combo.setCurrentIndex(
            panel.light_count_combo.findData(8))
        APP.processEvents()
        self.assertAlmostEqual(panel.config.light_x, -2.4)
        self.assertAlmostEqual(panel.config.specular, 0.9)
        self.assertAlmostEqual(panel.config.shadow_bias, 0.006)
        self.assertEqual(panel.config.pcf_radius, 2)
        self.assertEqual(panel.config.render_path, "deferred")
        self.assertEqual(panel.config.light_count, 8)
        self.assertEqual(window.canvas.render_revision, runtime_revision)
        self.assertEqual(window.canvas.history_manager.current_index, runtime_history)
        window.close()


if __name__ == "__main__":
    unittest.main()
