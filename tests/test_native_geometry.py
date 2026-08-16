import math
import os
import random
import sys
import unittest


SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from core import native_geometry
from core import stroke_tessellation as reference
from core.canvas import Canvas
from core.geometry import GeometryCache
from core.gpu_buffers import GpuBufferBuilder


def assert_mesh_close(test_case, expected, actual, places=11):
    test_case.assertEqual(len(expected), len(actual))
    for expected_point, actual_point in zip(expected, actual):
        test_case.assertEqual(len(expected_point), len(actual_point))
        for expected_value, actual_value in zip(expected_point, actual_point):
            test_case.assertAlmostEqual(expected_value, actual_value, places=places)


class NativeGeometryTests(unittest.TestCase):
    def tearDown(self):
        native_geometry.set_native_enabled(True)

    def test_python_fallback_is_always_available(self):
        native_geometry.set_native_enabled(False)
        points = ((0, 0), (50, 0), (50, 30))
        expected = reference.tessellate_stroke_coverage(
            points, 7, join="round", cap="square")
        actual = native_geometry.tessellate_stroke_coverage(
            points, 7, join="round", cap="square")

        self.assertEqual(native_geometry.backend_name(), "Python reference")
        self.assertEqual(expected, actual)

    @unittest.skipUnless(native_geometry.is_available(), "native module not built")
    def test_all_join_cap_and_closed_modes_match_reference(self):
        paths = (
            (((0, 0), (80, 0)), False),
            (((0, 0), (50, 0), (50, 40)), False),
            (((0, 0), (60, 0), (60, 30), (0, 30)), True),
            (((0, 0), (0, 0), (20, 0)), False),
        )
        for points, closed in paths:
            for join in ("miter", "bevel", "round"):
                for cap in ("butt", "square", "round"):
                    with self.subTest(points=points, closed=closed, join=join, cap=cap):
                        expected = reference.tessellate_stroke(
                            points, 8, closed, join, cap, 2.5, 8)
                        actual = native_geometry.tessellate_stroke(
                            points, 8, closed, join, cap, 2.5, 8)
                        assert_mesh_close(self, expected, actual)
                        expected_coverage = reference.tessellate_stroke_coverage(
                            points, 8, closed, join, cap, 1.0, 2.5, 8)
                        actual_coverage = native_geometry.tessellate_stroke_coverage(
                            points, 8, closed, join, cap, 1.0, 2.5, 8)
                        assert_mesh_close(self, expected_coverage, actual_coverage)

    @unittest.skipUnless(native_geometry.is_available(), "native module not built")
    def test_deterministic_random_paths_are_finite_and_match(self):
        generator = random.Random(20260728)
        for _ in range(20):
            points = tuple((generator.uniform(-100, 100), generator.uniform(-100, 100))
                           for _ in range(generator.randint(2, 12)))
            width = generator.uniform(0.1, 30.0)
            expected = reference.tessellate_stroke_coverage(
                points, width, join="round", cap="round", round_segments=6)
            actual = native_geometry.tessellate_stroke_coverage(
                points, width, join="round", cap="round", round_segments=6)
            self.assertTrue(all(math.isfinite(value) for point in actual for value in point))
            assert_mesh_close(self, expected, actual, places=10)

    @unittest.skipUnless(native_geometry.is_available(), "native module not built")
    def test_gpu_frame_is_equivalent_with_python_and_native_kernels(self):
        canvas = Canvas(500, 300)
        canvas.add_shape(canvas.create_rectangle(20, 20, 80, 50))
        canvas.add_shape(canvas.create_ellipse(150, 20, 80, 60))
        cache = GeometryCache()
        cache.sync_snapshot(canvas.create_render_snapshot())
        builder = GpuBufferBuilder()

        native_geometry.set_native_enabled(False)
        python_frame = builder.build(cache)
        native_geometry.set_native_enabled(True)
        native_frame = builder.build(cache)

        self.assertEqual(python_frame.batches, native_frame.batches)
        self.assertEqual(python_frame.command_stream, native_frame.command_stream)
        self.assertEqual(len(python_frame.vertices), len(native_frame.vertices))
        for expected, actual in zip(python_frame.vertices, native_frame.vertices):
            self.assertAlmostEqual(expected, actual, places=10)


if __name__ == "__main__":
    unittest.main()
