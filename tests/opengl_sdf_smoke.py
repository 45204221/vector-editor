"""Real-context framebuffer signature smoke test for the M21.5 SDF page."""
import hashlib
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path: sys.path.insert(0, SRC)

from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from ui.sdf_panel import SdfPanel


def capture(panel, label):
    panel.viewport.update(); QTest.qWait(120)
    image = panel.viewport.grabFramebuffer(); bits = image.bits(); bits.setsize(image.byteCount())
    return label, hashlib.sha1(bytes(bits)).hexdigest()[:16]


def main():
    app = QApplication.instance() or QApplication([])
    panel = SdfPanel(); panel.resize(900, 760); panel.show(); QTest.qWait(300)
    report = {}; failures = []
    for index, label in enumerate(("final", "mask", "distance", "contours")):
        panel.view_combo.setCurrentIndex(index); key, signature = capture(panel, label); report[key] = signature
    rebuilds = panel.viewport.rebuilds; uploads = panel.viewport.uploads
    panel.view_combo.setCurrentIndex(0)
    panel.scale_slider.setValue(25); report["scale_025"] = capture(panel,"x")[1]
    panel.scale_slider.setValue(800); report["scale_8"] = capture(panel,"x")[1]
    state = panel.viewport.runtime_state(); report["state"] = state
    if len(set(value for value in report.values() if isinstance(value,str))) < 6:
        failures.append("debug/scale signatures are not distinct")
    if panel.viewport.rebuilds != rebuilds or panel.viewport.uploads != uploads:
        failures.append("uniform-only scale change rebuilt/uploaded SDF")
    if not state["valid"] or state["error"]: failures.append("OpenGL SDF viewport invalid")
    panel.close(); app.processEvents(); print(json.dumps({"report":report,"failures":failures},ensure_ascii=False,indent=2))
    return 1 if failures else 0


if __name__ == "__main__": raise SystemExit(main())
