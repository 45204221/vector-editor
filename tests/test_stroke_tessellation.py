import math
import os
import sys
import unittest


SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from core.stroke_tessellation import (tessellate_segments, tessellate_stroke,
                                      tessellate_stroke_coverage)


def bounds(points):
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


class StrokeTessellationTests(unittest.TestCase):
    def test_horizontal_butt_stroke_has_exact_width(self):
        triangles = tessellate_stroke(((0, 0), (100, 0)), 10)
        self.assertEqual(len(triangles), 6)
        self.assertEqual(bounds(triangles), (0.0, -5.0, 100.0, 5.0))

    def test_square_and_round_caps_extend_by_half_width(self):
        square = tessellate_stroke(((0, 0), (100, 0)), 10, cap="square")
        rounded = tessellate_stroke(((0, 0), (100, 0)), 10, cap="round")
        self.assertEqual(bounds(square), (-5.0, -5.0, 105.0, 5.0))
        rounded_bounds = bounds(rounded)
        for actual, expected in zip(rounded_bounds, (-5.0, -5.0, 105.0, 5.0)):
            self.assertAlmostEqual(actual, expected, places=6)
        self.assertGreater(len(rounded), len(square))

    def test_join_modes_generate_finite_triangle_lists(self):
        path = ((0, 0), (50, 0), (50, 50))
        results = {join: tessellate_stroke(path, 8, join=join)
                   for join in ("miter", "bevel", "round")}
        for triangles in results.values():
            self.assertTrue(triangles)
            self.assertEqual(len(triangles) % 3, 0)
            self.assertTrue(all(math.isfinite(component)
                                for point in triangles for component in point))
        self.assertGreater(len(results["round"]), len(results["bevel"]))

    def test_miter_limit_prevents_acute_spikes(self):
        triangles = tessellate_stroke(
            ((0, 0), (50, 0), (1, 1)), 10, join="miter", miter_limit=2)
        self.assertLessEqual(max(math.hypot(x - 50, y) for x, y in triangles), 55.0)

    def test_duplicate_points_and_independent_segments_are_safe(self):
        repeated = tessellate_stroke(((0, 0), (0, 0), (10, 0)), 4)
        independent = tessellate_segments(((0, 0), (10, 0), (20, 0), (20, 10)), 4)
        self.assertEqual(len(repeated), 6)
        self.assertEqual(len(independent), 12)

    def test_closed_rectangle_has_four_bodies_and_four_joins(self):
        triangles = tessellate_stroke(
            ((0, 0), (20, 0), (20, 10), (0, 10)), 2, closed=True)
        self.assertEqual(len(triangles), 36)
        self.assertEqual(len(triangles) % 3, 0)

    def test_coverage_fringe_adds_transparent_one_pixel_border(self):
        mesh = tessellate_stroke_coverage(((0, 0), (100, 0)), 10, cap="butt")
        coverages = {coverage for _, _, coverage in mesh}

        self.assertEqual(coverages, {0.0, 1.0})
        self.assertEqual(bounds([(x, y) for x, y, _ in mesh]),
                         (-1.0, -6.0, 101.0, 6.0))
        self.assertEqual(len(mesh) % 3, 0)


if __name__ == "__main__":
    unittest.main()
