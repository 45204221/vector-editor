import math
import os
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtWidgets import QApplication
from core import native_hdr
from core.hdr_postprocess import (CanvasHdrConfig, ToneMappingConfig,
                                  linear_to_srgb, relative_luminance,
                                  srgb_to_linear, tone_map_rgb)
from ui.main_window import MainWindow


APP = QApplication.instance() or QApplication([])


class HdrToneMappingTests(unittest.TestCase):
    def test_canvas_config_is_shared_tone_mapping_contract(self):
        self.assertIs(CanvasHdrConfig, ToneMappingConfig)

    def test_config_validation_and_changes(self):
        config = CanvasHdrConfig()
        self.assertEqual(config.as_dict(), {
            "enabled": False, "tone_mapper": "reinhard",
            "exposure": 1.0, "debug_view": "final",
        })
        changed = config.changed(True, "aces", 2.5, "heatmap")
        self.assertTrue(changed.enabled)
        self.assertEqual(changed.tone_mapper, "aces")
        self.assertEqual(changed.exposure, 2.5)
        with self.assertRaises(ValueError):
            CanvasHdrConfig(tone_mapper="unknown")
        with self.assertRaises(ValueError):
            CanvasHdrConfig(exposure=0.0)

    def test_linear_reinhard_and_aces_golden_values(self):
        linear = tone_map_rgb((4.0, 1.0, 0.25), 1.0, "linear")
        self.assertAlmostEqual(linear[0], 1.0)
        self.assertAlmostEqual(linear[1], 1.0)
        self.assertAlmostEqual(linear[2], 0.25 ** (1.0 / 2.2))
        reinhard = tone_map_rgb((4.0, 1.0, 0.25), 1.0, "reinhard")
        self.assertAlmostEqual(reinhard[0], (4.0 / 5.0) ** (1.0 / 2.2))
        aces = tone_map_rgb((4.0, 1.0, 0.25), 1.0, "aces")
        self.assertNotEqual(aces, linear)
        self.assertNotEqual(aces, reinhard)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in aces))

    def test_invalid_reference_inputs(self):
        for arguments in (((1, 2), 1.0, "linear"),
                          ((-1, 0, 0), 1.0, "linear"),
                          ((math.inf, 0, 0), 1.0, "linear")):
            with self.assertRaises(ValueError):
                tone_map_rgb(*arguments)

    def test_srgb_round_trip_and_luminance(self):
        for encoded in (0.0, 0.02, 0.18, 0.5, 1.0):
            self.assertAlmostEqual(
                linear_to_srgb(srgb_to_linear(encoded)), encoded, places=12)
        self.assertAlmostEqual(relative_luminance((1.0, 1.0, 1.0)), 1.0)
        self.assertAlmostEqual(relative_luminance((1.0, 0.0, 0.0)), 0.2126)
        with self.assertRaises(ValueError):
            srgb_to_linear(1.1)
        with self.assertRaises(ValueError):
            linear_to_srgb(-0.1)
        with self.assertRaises(ValueError):
            relative_luminance((1.0, 0.0))

    @unittest.skipUnless(native_hdr.is_available(), "native HDR ABI not built")
    def test_cpp_python_parity(self):
        for operator in ("linear", "reinhard", "aces"):
            for color, exposure in (((4.0, 2.0, 0.5), 1.0),
                                    ((0.1, 1.25, 8.0), 2.5)):
                actual, backend = native_hdr.tone_map_rgb(
                    color, exposure, operator)
                expected = tone_map_rgb(color, exposure, operator)
                self.assertEqual(backend, "C++ native")
                for first, second in zip(actual, expected):
                    self.assertAlmostEqual(first, second, places=12)


class CanvasHdrUiTests(unittest.TestCase):
    def test_controls_are_history_neutral_and_forwarded(self):
        window = MainWindow()
        canvas = window.canvas
        revision = canvas.render_revision
        history = canvas.history_manager.current_index
        panel = window.pipeline_panel
        panel.hdr_enabled_check.setChecked(True)
        panel.hdr_tone_combo.setCurrentIndex(
            panel.hdr_tone_combo.findData("aces"))
        panel.hdr_exposure_spin.setValue(3.0)
        panel.hdr_debug_combo.setCurrentIndex(
            panel.hdr_debug_combo.findData("overexposure"))
        APP.processEvents()
        config = window.graphics_view.hdr_config
        self.assertTrue(config.enabled)
        self.assertEqual(config.tone_mapper, "aces")
        self.assertEqual(config.exposure, 3.0)
        self.assertEqual(config.debug_view, "overexposure")
        self.assertEqual(canvas.render_revision, revision)
        self.assertEqual(canvas.history_manager.current_index, history)
        state = window.graphics_view.canvas_hdr_state()
        self.assertFalse(state["active"])
        self.assertIn("不是 OpenGL", state["error"])
        window.close()


if __name__ == "__main__":
    unittest.main()
