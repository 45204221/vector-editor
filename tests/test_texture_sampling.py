import os
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QSplitter
from core import native_texture
from core.texture_sampling import (MipLevel, build_checker_texture,
                                   generate_mipmaps, sample_anisotropic,
                                   sample_mipmaps, texture_footprint)
from ui.main_window import MainWindow


APP = QApplication.instance() or QApplication([])


class TextureSamplingTests(unittest.TestCase):
    def test_checker_is_deterministic_rgba8(self):
        first = build_checker_texture(64)
        self.assertEqual(first, build_checker_texture(64))
        self.assertEqual(len(first), 64 * 64 * 4)
        self.assertTrue(all(first[index] == 255 for index in range(3, len(first), 4)))

    def test_mip_chain_reaches_one_by_one(self):
        levels = generate_mipmaps(build_checker_texture(256), 256, 256)
        self.assertEqual(len(levels), 9)
        self.assertEqual([(level.width, level.height) for level in levels],
                         [(256 >> index, 256 >> index) for index in range(9)])
        self.assertEqual((levels[-1].width, levels[-1].height), (1, 1))

    def test_box_filter_golden_value(self):
        source = bytes((0, 10, 20, 255, 20, 30, 40, 255,
                        40, 50, 60, 255, 60, 70, 80, 255))
        levels = generate_mipmaps(source, 2, 2)
        self.assertEqual(levels[1].rgba, bytes((30, 40, 50, 255)))

    def test_odd_edge_is_preserved_by_clamped_box(self):
        source = bytes((10, 0, 0, 255, 30, 0, 0, 255, 90, 0, 0, 255))
        levels = generate_mipmaps(source, 3, 1)
        self.assertEqual([(level.width, level.height) for level in levels],
                         [(3, 1), (2, 1), (1, 1)])
        self.assertEqual(levels[1].rgba[0], 20)
        self.assertEqual(levels[1].rgba[4], 90)

    def test_nearest_bilinear_trilinear_and_wrap(self):
        source = bytes((0, 0, 0, 255, 200, 0, 0, 255,
                        0, 200, 0, 255, 200, 200, 0, 255))
        levels = generate_mipmaps(source, 2, 2)
        self.assertEqual(sample_mipmaps(levels, 0.25, 0.25, 0, "nearest"),
                         (0, 0, 0, 255))
        self.assertEqual(sample_mipmaps(levels, 0.5, 0.5, 0, "bilinear"),
                         (100, 100, 0, 255))
        self.assertEqual(sample_mipmaps(levels, 0.5, 0.5, 0.5, "trilinear"),
                         (100, 100, 0, 255))
        self.assertEqual(sample_mipmaps(levels, 1.25, 0.25, 0, "nearest", True),
                         (0, 0, 0, 255))
        self.assertEqual(sample_mipmaps(levels, 1.25, 0.25, 0, "nearest", False),
                         (200, 0, 0, 255))

    def test_invalid_contracts(self):
        with self.assertRaises(ValueError):
            generate_mipmaps(b"", 0, 1)
        with self.assertRaises(ValueError):
            generate_mipmaps(b"1234", 2, 2)
        with self.assertRaises(ValueError):
            sample_mipmaps((MipLevel(1, 1, b"\0\0\0\xff"),),
                           0, 0, 0, "unknown")
        with self.assertRaises(ValueError):
            texture_footprint(256, 256, 0.1, 0, 0, 0.1, 3)

    def test_footprint_axes_lod_and_tap_budget(self):
        footprint = texture_footprint(
            256, 256, 8 / 256, 0, 0, 2 / 256, 8)
        self.assertAlmostEqual(footprint.major, 8.0)
        self.assertAlmostEqual(footprint.minor, 2.0)
        self.assertAlmostEqual(footprint.ratio, 4.0)
        self.assertAlmostEqual(footprint.isotropic_lod, 3.0)
        self.assertAlmostEqual(footprint.anisotropic_lod, 1.0)
        self.assertEqual(footprint.taps, 4)
        self.assertAlmostEqual(abs(footprint.direction_u), 1.0)
        self.assertAlmostEqual(footprint.direction_v, 0.0)
        self.assertEqual(texture_footprint(
            256, 256, 16 / 256, 0, 0, 1 / 256, 2).taps, 2)

    def test_anisotropic_sampling_is_deterministic(self):
        levels = generate_mipmaps(build_checker_texture(64), 64, 64)
        first, footprint = sample_anisotropic(
            levels, 0.13, 0.27, 8 / 64, 0, 0, 2 / 64, 8)
        second, _ = sample_anisotropic(
            levels, 0.13, 0.27, 8 / 64, 0, 0, 2 / 64, 8)
        self.assertEqual(first, second)
        self.assertEqual(footprint.taps, 4)
        self.assertTrue(all(0 <= channel <= 255 for channel in first))

    @unittest.skipUnless(native_texture.is_available(), "native texture ABI not built")
    def test_cpp_python_mip_and_sample_parity(self):
        source = build_checker_texture(32)
        reference = generate_mipmaps(source, 32, 32)
        actual, backend = native_texture.generate_mipmaps(source, 32, 32)
        self.assertEqual(backend, "C++ native")
        self.assertEqual(actual, reference)
        for filter_mode in ("nearest", "bilinear", "trilinear"):
            for repeat in (False, True):
                for u, v, lod in ((0.125, 0.375, 0.0), (1.2, -0.1, 2.4),
                                  (0.83, 0.61, 4.0)):
                    color, sample_backend = native_texture.sample_texture(
                        source, 32, 32, u, v, lod, filter_mode, repeat)
                    self.assertEqual(sample_backend, "C++ native")
                    self.assertEqual(color, sample_mipmaps(
                        reference, u, v, lod, filter_mode, repeat))
        actual, footprint, backend = native_texture.sample_anisotropic(
            source, 32, 32, 0.21, 0.37, 8 / 32, 0, 0, 2 / 32, 8, True)
        expected, expected_footprint = sample_anisotropic(
            reference, 0.21, 0.37, 8 / 32, 0, 0, 2 / 32, 8, True)
        self.assertEqual(backend, "C++ native")
        self.assertEqual(actual, expected)
        for field in expected_footprint.__dataclass_fields__:
            self.assertAlmostEqual(getattr(footprint, field),
                                   getattr(expected_footprint, field))


class TextureSamplingPanelTests(unittest.TestCase):
    def test_engine_lab_page_and_controls_are_history_neutral(self):
        window = MainWindow(); panel = window.texture_sampling_panel
        revision = window.canvas.render_revision
        history = window.canvas.history_manager.current_index
        window.show_texture_sampling_panel(); APP.processEvents()
        self.assertEqual(window.engine_lab_window.pages.currentIndex(), 5)
        self.assertIsInstance(panel.findChild(QSplitter, "texture_lod_splitter"), QSplitter)
        self.assertIn(panel.backend, ("C++ native", "Python reference"))
        self.assertEqual(len(panel.mip_levels), 9)
        panel.filter_combo.setCurrentIndex(0)
        panel.view_combo.setCurrentIndex(2)
        panel.anisotropic_check.setChecked(True)
        panel.tap_combo.setCurrentIndex(panel.tap_combo.findData(4))
        panel.manual_lod_check.setChecked(True); panel.lod_slider.setValue(6)
        panel.probe_u.setValue(1.25); panel.probe_v.setValue(-0.25)
        APP.processEvents()
        self.assertIn("|Δ| (0, 0, 0, 0)", panel.probe_label.text())
        self.assertIn("ratio", panel.footprint_label.text())
        self.assertTrue(panel.viewport.anisotropic)
        self.assertEqual(panel.viewport.max_taps, 4)
        self.assertEqual(window.canvas.render_revision, revision)
        self.assertEqual(window.canvas.history_manager.current_index, history)
        panel.animate_check.setChecked(True); APP.processEvents()
        self.assertTrue(panel.timer.isActive())
        window.engine_lab_window.hide(); APP.processEvents()
        self.assertFalse(panel.timer.isActive())
        window.close()


if __name__ == "__main__":
    unittest.main()
