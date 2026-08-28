"""Small, defensive QSettings boundary for window-only UI state."""

from PyQt5.QtCore import QSettings
from PyQt5.QtGui import QGuiApplication


def persistence_enabled():
    app = QGuiApplication.instance()
    return bool(app is not None and app.platformName().lower() != "offscreen")


def settings():
    return QSettings("VectorEditorDemo", "VectorEditor")


def clamp_window_to_screens(window):
    screens = QGuiApplication.screens()
    if not screens:
        return
    frame = window.frameGeometry()
    screen = next((item for item in screens
                   if item.availableGeometry().contains(frame.center())),
                  QGuiApplication.primaryScreen())
    area = screen.availableGeometry()
    width = min(max(window.minimumWidth(), window.width()), area.width())
    height = min(max(window.minimumHeight(), window.height()), area.height())
    x = min(max(window.x(), area.left()), area.right() - width + 1)
    y = min(max(window.y(), area.top()), area.bottom() - height + 1)
    window.resize(width, height); window.move(x, y)


def restore_window(window, geometry_key, state_key=None):
    if not persistence_enabled(): return
    store = settings()
    geometry = store.value(geometry_key)
    if geometry:
        try: window.restoreGeometry(geometry)
        except (TypeError, ValueError): pass
    if state_key:
        state = store.value(state_key)
        if state:
            try: window.restoreState(state)
            except (TypeError, ValueError): pass
    clamp_window_to_screens(window)


def save_window(window, geometry_key, state_key=None):
    if not persistence_enabled(): return
    store = settings(); store.setValue(geometry_key, window.saveGeometry())
    if state_key: store.setValue(state_key, window.saveState())
