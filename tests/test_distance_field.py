import math
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from core.distance_field import (encode_signed_distance_rgba8,
                                 euclidean_distance_transform,
                                 signed_distance_field)
from core.native_distance_field import signed_distance_field as native_sdf
from PyQt5.QtWidgets import QApplication
from ui.sdf_panel import SdfPanel

APP = QApplication.instance() or QApplication([])


class DistanceFieldTests(unittest.TestCase):
    def test_exact_single_feature_distances(self):
        values = euclidean_distance_transform((0, 0, 0, 0, 1, 0, 0, 0, 0), 3, 3)
        self.assertEqual(values[4], 0.0)
        self.assertEqual(values[1], 1.0)
        self.assertAlmostEqual(values[0], math.sqrt(2.0))

    def test_signed_field_is_positive_inside(self):
        field = signed_distance_field((0, 0, 0, 0, 1, 0, 0, 0, 0), 3, 3)
        self.assertEqual(field[4], 1.0)
        self.assertEqual(field[1], -1.0)
        self.assertAlmostEqual(field[0], -math.sqrt(2.0))

    def test_native_python_parity(self):
        mask = tuple((x - 4) ** 2 + (y - 4) ** 2 <= 9
                     for y in range(9) for x in range(9))
        reference = signed_distance_field(mask, 9, 9)
        actual, backend = native_sdf(mask, 9, 9)
        self.assertIn(backend, ("C++ native exact EDT", "Python exact EDT"))
        self.assertEqual(len(actual), len(reference))
        self.assertLess(max(abs(a - b) for a, b in zip(actual, reference)), 1.0e-9)

    def test_invalid_size_and_encode_range(self):
        with self.assertRaises(ValueError):
            signed_distance_field((1,), 2, 2)
        with self.assertRaises(ValueError):
            encode_signed_distance_rgba8((0.0,), 0.0)
        self.assertEqual(encode_signed_distance_rgba8((-2.0, 0.0, 2.0), 2.0),
                         bytes((0, 0, 0, 255, 128, 128, 128, 255,
                                255, 255, 255, 255)))

    def test_ui_uniform_changes_do_not_rebuild_field(self):
        panel = SdfPanel()
        initial = panel.viewport.rebuilds
        panel.scale_slider.setValue(250)
        panel.outline_spin.setValue(4.0)
        panel.glow_spin.setValue(8.0)
        self.assertEqual(panel.viewport.rebuilds, initial)
        panel.source_combo.setCurrentIndex(1)
        self.assertEqual(panel.viewport.rebuilds, initial + 1)


if __name__ == "__main__":
    unittest.main()
