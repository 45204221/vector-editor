import math
import os
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtGui import QImage, QPainter, QTransform
from PyQt5.QtWidgets import QApplication

from core import native_geometry
from core.canvas import Canvas
from core.lighting_experiment import (MAX_LIGHTS, LightSource, LightingConfig,
                                      build_lighting_snapshot,
                                      draw_lighting_debug,
                                      extract_occluder_segments)
from core.lighting_gpu import (build_light_fan, build_multi_light_fan,
                               device_light_parameters, estimated_lighting_bytes)
from core.native_visibility import visibility_polygon as native_visibility
from core.visibility import ray_segment_intersection, visibility_polygon
from ui.main_window import MainWindow


APP = QApplication.instance() or QApplication([])


def boundary(width=100, height=80):
    return (((0, 0), (width, 0)), ((width, 0), (width, height)),
            ((width, height), (0, height)), ((0, height), (0, 0)))


class VisibilityAlgorithmTests(unittest.TestCase):
    def test_ray_segment_hit_parallel_and_nearest_geometry(self):
        hit = ray_segment_intersection((0, 0), (1, 0), ((5, -2), (5, 2)))
        self.assertEqual(hit, (5.0, (5.0, 0.0)))
        self.assertIsNone(ray_segment_intersection(
            (0, 0), (1, 0), ((0, 2), (5, 2))))
        self.assertIsNone(ray_segment_intersection(
            (0, 0), (-1, 0), ((5, -2), (5, 2))))

    def test_canvas_boundary_produces_sorted_finite_polygon(self):
        result = visibility_polygon((50, 40), boundary())
        self.assertGreaterEqual(len(result.polygon), 4)
        self.assertEqual(len(result.polygon), len(result.rays))
        self.assertEqual(result.intersection_tests, 4 * 2 * 3 * 4)
        self.assertEqual(list(result.rays), sorted(result.rays,
                                                   key=lambda ray: ray.angle))
        for x, y in result.polygon:
            self.assertGreaterEqual(x, -1e-4); self.assertLessEqual(x, 100.0001)
            self.assertGreaterEqual(y, -1e-4); self.assertLessEqual(y, 80.0001)

    def test_nearer_occluder_wins(self):
        segments = boundary() + (((70, 20), (70, 60)),)
        result = visibility_polygon((20, 40), segments)
        occluder_hits = [ray for ray in result.rays if ray.segment_index == 4]
        self.assertGreaterEqual(len(occluder_hits), 4)
        self.assertTrue(all(abs(ray.point[0] - 70.0) < 1e-6
                            for ray in occluder_hits))
        self.assertTrue(any(abs(ray.point[1] - 20.0) < 0.01
                            for ray in occluder_hits))
        self.assertTrue(any(abs(ray.point[1] - 60.0) < 0.01
                            for ray in occluder_hits))

    @unittest.skipUnless(native_geometry.is_available(), "native module not built")
    def test_cpp_matches_python_reference(self):
        segments = boundary() + (
            ((30, 15), (55, 15)), ((55, 15), (55, 50)),
            ((55, 50), (30, 50)), ((30, 50), (30, 15)),
        )
        reference = visibility_polygon((18, 32), segments)
        actual = native_visibility((18, 32), segments, use_native=True)
        self.assertEqual(actual.backend, "C++ native")
        self.assertEqual(actual.intersection_tests, reference.intersection_tests)
        self.assertEqual(len(actual.polygon), len(reference.polygon))
        for first, second in zip(actual.polygon, reference.polygon):
            self.assertAlmostEqual(first[0], second[0], places=8)
            self.assertAlmostEqual(first[1], second[1], places=8)


class VisibilityIntegrationTests(unittest.TestCase):
    def test_gpu_fan_payload_and_device_parameters(self):
        canvas = Canvas(300, 200)
        config = LightingConfig(enabled=True, light_x=50, light_y=40, radius=25)
        snapshot = build_lighting_snapshot(canvas, None, config)
        fan = build_light_fan(snapshot)
        self.assertEqual(fan.vertex_count, len(snapshot.result.polygon) + 2)
        self.assertEqual(len(fan.payload), fan.vertex_count * 8)
        self.assertEqual(build_light_fan(snapshot), fan)
        transform = QTransform(); transform.translate(10, 20); transform.scale(2, 2)
        self.assertEqual(device_light_parameters(transform, config), (110.0, 100.0, 50.0))
        self.assertEqual(estimated_lighting_bytes(320, 200), 512000)

    def test_multi_light_snapshot_and_combined_fan_ranges(self):
        canvas = Canvas(300, 200)
        extra = LightSource(220, 140, 80, 0.8, "#68B8FF")
        config = LightingConfig(enabled=True, light_x=50, light_y=40,
                                extra_lights=(extra,), selected_light=1)
        snapshot = build_lighting_snapshot(canvas, None, config)
        self.assertEqual(len(snapshot.light_visibilities), 2)
        self.assertIs(snapshot.result, snapshot.light_visibilities[1].result)
        frame = build_multi_light_fan(snapshot)
        self.assertEqual(len(frame.ranges), 2)
        self.assertEqual(frame.vertex_count,
                         sum(item.vertex_count for item in frame.ranges))
        self.assertEqual(len(frame.payload), frame.vertex_count * 8)
        self.assertEqual(frame.ranges[1].first_vertex,
                         frame.ranges[0].vertex_count)

    def test_light_limit_and_runtime_cache_excludes_uniform_only_changes(self):
        lights = tuple(LightSource(20 + index * 10, 30) for index in range(7))
        config = LightingConfig(extra_lights=lights)
        self.assertEqual(len(config.light_sources()), MAX_LIGHTS)
        with self.assertRaises(ValueError):
            LightingConfig(extra_lights=lights + (LightSource(100, 100),))

        window = MainWindow(); view = window.graphics_view
        view.set_lighting_experiment(enabled=True)
        first = view.lighting_snapshot()
        builds = view.lighting_experiment_state()["visibility_build_count"]
        view.set_selected_light_parameters(color="#68B8FF", radius=333)
        rebound = view.lighting_snapshot()
        state = view.lighting_experiment_state()
        self.assertIs(first.result, rebound.result)
        self.assertEqual(state["visibility_build_count"], builds)
        self.assertGreaterEqual(state["visibility_cache_hits"], 1)
        view.set_selected_light_parameters(x=first.config.light_x + 10)
        moved = view.lighting_snapshot()
        self.assertIsNot(first.result, moved.result)
        self.assertEqual(view.lighting_experiment_state()["visibility_build_count"],
                         builds + 1)
        window.close()

    def test_real_closed_geometry_and_layer_visibility_feed_segments(self):
        canvas = Canvas(300, 200)
        shape = canvas.create_rectangle(20, 30, 80, 50)
        canvas.add_shape(shape)
        segments, truncated = extract_occluder_segments(canvas)
        self.assertFalse(truncated)
        self.assertEqual(len(segments), 8)
        self.assertIn(((20.0, 30.0), (100.0, 30.0)), segments)

        canvas.set_layer_visibility("content", False)
        hidden, _ = extract_occluder_segments(canvas)
        self.assertEqual(len(hidden), 4)

    def test_debug_overlay_draws_without_mutating_document(self):
        canvas = Canvas(300, 200)
        canvas.add_shape(canvas.create_rectangle(100, 60, 60, 50))
        revision = canvas.render_revision
        history = canvas.history_manager.current_index
        config = LightingConfig(True, 60, 100, 120, 1, 0.2,
                                "#FFD36A", "combined", 1e-5, False)
        snapshot = build_lighting_snapshot(canvas, None, config)
        image = QImage(300, 200, QImage.Format_ARGB32)
        image.fill(0xFFFFFFFF)
        painter = QPainter(image); draw_lighting_debug(painter, snapshot); painter.end()
        self.assertTrue(any(image.pixelColor(x, y).red() < 250
                            for x in range(0, 300, 5) for y in range(0, 200, 5)))
        self.assertEqual(canvas.render_revision, revision)
        self.assertEqual(canvas.history_manager.current_index, history)

    def test_engine_lab_controls_are_history_neutral(self):
        window = MainWindow()
        revision = window.canvas.render_revision
        history = window.canvas.history_manager.current_index
        window.show_lighting_panel(); APP.processEvents()
        panel = window.lighting_panel
        panel.enabled_check.setChecked(True)
        panel.gpu_check.setChecked(True)
        panel.debug_combo.setCurrentIndex(panel.debug_combo.findData("final"))
        panel.x_spin.setValue(420); panel.y_spin.setValue(260)
        APP.processEvents()
        state = window.graphics_view.lighting_experiment_state()
        self.assertEqual(window.engine_lab_window.pages.currentIndex(), 3)
        self.assertTrue(state["enabled"])
        self.assertTrue(state["gpu_lighting"])
        self.assertFalse(state["gpu_supported"])
        self.assertIn("OpenGL", state["error"])
        self.assertTrue(window.graphics_view.add_lighting_source())
        APP.processEvents()
        self.assertEqual(window.graphics_view.lighting_experiment_state()["light_count"], 2)
        self.assertEqual(panel.light_combo.count(), 2)
        self.assertTrue(window.graphics_view.remove_selected_lighting_source())
        self.assertGreaterEqual(state["segments"], 4)
        self.assertGreater(state["polygon_points"], 0)
        self.assertEqual(window.canvas.render_revision, revision)
        self.assertEqual(window.canvas.history_manager.current_index, history)
        window.close()


if __name__ == "__main__":
    unittest.main()
