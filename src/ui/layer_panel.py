"""可操作的图层面板。"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
                             QListWidgetItem, QPushButton, QInputDialog, QGroupBox,
                             QFormLayout, QSpinBox, QLabel)


class LayerPanel(QWidget):
    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        layout = QVBoxLayout(self)
        visibility_hint = QLabel("勾选图层表示显示，取消勾选表示隐藏")
        visibility_hint.setWordWrap(True)
        layout.addWidget(visibility_hint)
        self.list = QListWidget(); layout.addWidget(self.list)
        management_buttons = QHBoxLayout()
        for text, handler in (("+", self.add_layer), ("删除", self.remove_layer),
                              ("放入", self.move_selection_here)):
            button = QPushButton(text); button.clicked.connect(handler); management_buttons.addWidget(button)
        layout.addLayout(management_buttons)
        state_buttons = QHBoxLayout()
        self.visibility_button = QPushButton("隐藏图层")
        self.visibility_button.setToolTip("切换当前图层的显示或隐藏状态")
        self.visibility_button.clicked.connect(self.toggle_current_visibility)
        state_buttons.addWidget(self.visibility_button)
        for text, handler in (("锁定", self.toggle_current_lock),
                              ("上移", lambda: self.move_layer(-1)),
                              ("下移", lambda: self.move_layer(1))):
            button = QPushButton(text); button.clicked.connect(handler); state_buttons.addWidget(button)
        layout.addLayout(state_buttons)

        transform_group = QGroupBox("活动图层变换")
        transform_layout = QFormLayout(transform_group)
        self.offset_x = QSpinBox(); self.offset_x.setRange(-2000, 2000); self.offset_x.setSuffix(" px")
        self.offset_y = QSpinBox(); self.offset_y.setRange(-2000, 2000); self.offset_y.setSuffix(" px")
        self.rotation = QSpinBox(); self.rotation.setRange(-360, 360); self.rotation.setSuffix("°")
        self.scale = QSpinBox(); self.scale.setRange(10, 500); self.scale.setValue(100); self.scale.setSuffix("%")
        transform_layout.addRow("平移 X", self.offset_x)
        transform_layout.addRow("平移 Y", self.offset_y)
        transform_layout.addRow("旋转", self.rotation)
        transform_layout.addRow("缩放", self.scale)
        transform_buttons = QHBoxLayout()
        move_button = QPushButton("应用平移"); move_button.clicked.connect(self.apply_translation); transform_buttons.addWidget(move_button)
        rotate_button = QPushButton("应用旋转"); rotate_button.clicked.connect(self.apply_rotation); transform_buttons.addWidget(rotate_button)
        scale_button = QPushButton("应用缩放"); scale_button.clicked.connect(self.apply_scale); transform_buttons.addWidget(scale_button)
        transform_layout.addRow(transform_buttons)
        layout.addWidget(transform_group)
        self.list.itemChanged.connect(self.update_layer_state)
        self.list.currentItemChanged.connect(self.on_current_layer_changed)
        # Physics/render changes may arrive at 60 Hz and must never destroy the
        # QListWidget items while the user is selecting a layer.
        self.canvas.layers_changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        current = self.canvas.layer_manager.active_layer_id
        self.list.blockSignals(True); self.list.clear()
        for layer in self.canvas.layer_manager.layers:
            active_mark = "● " if layer.id == current else ""
            visibility = "显示" if layer.visible else "隐藏"
            lock_state = " | 已锁定" if layer.locked else ""
            item = QListWidgetItem(f"{active_mark}{layer.name} | {visibility}{lock_state}")
            item.setData(Qt.UserRole, layer.id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if layer.visible else Qt.Unchecked)
            item.setToolTip("勾选显示图层；取消勾选隐藏图层")
            self.list.addItem(item)
            if layer.id == current: self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self.update_visibility_button()

    def current_layer_id(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def add_layer(self):
        name, ok = QInputDialog.getText(self, "新建图层", "图层名称：")
        if ok and name.strip():
            self.canvas.layer_manager.add(name.strip())
            self.canvas.layer_manager.set_active(self.canvas.layer_manager.layers[-1].id)
            self.canvas.layers_changed.emit()
            self.canvas.canvas_changed.emit()
            self.canvas.record_history("新建图层")

    def remove_layer(self):
        layer_id = self.current_layer_id()
        if layer_id and self.canvas.layer_manager.remove(layer_id):
            for shape in self.canvas.shapes:
                if shape.layer_id == layer_id: shape.layer_id = "content"
            self.canvas.layers_changed.emit()
            self.canvas.update_world_state()
            self.canvas.record_history("删除图层")

    def move_layer(self, delta):
        self.canvas.reorder_layer(self.current_layer_id(), delta)

    def update_layer_state(self, item):
        self.canvas.set_layer_visibility(
            item.data(Qt.UserRole), item.checkState() == Qt.Checked)

    def toggle_current_visibility(self):
        layer = self.canvas.layer_manager.get(self.current_layer_id())
        if layer:
            self.canvas.set_layer_visibility(layer.id, not layer.visible)

    def update_visibility_button(self):
        layer = self.canvas.layer_manager.get(self.current_layer_id())
        if layer is None:
            self.visibility_button.setEnabled(False)
            self.visibility_button.setText("显示/隐藏")
            return
        self.visibility_button.setEnabled(True)
        self.visibility_button.setText("隐藏图层" if layer.visible else "显示图层")

    def toggle_current_lock(self):
        layer = self.canvas.layer_manager.get(self.current_layer_id())
        if layer:
            layer.locked = not layer.locked
            if layer.locked and self.canvas.layer_manager.active_layer_id == layer.id:
                self.canvas.layer_manager.set_active("content")
            self.canvas.layers_changed.emit()
            self.canvas.canvas_changed.emit()
            self.canvas.record_history("锁定图层")

    def move_selection_here(self):
        layer_id = self.current_layer_id()
        if layer_id:
            self.canvas.move_selected_to_layer(layer_id)

    def on_current_layer_changed(self, current, previous):
        if current:
            self.canvas.layer_manager.set_active(current.data(Qt.UserRole))
            self.refresh()

    def _active_layer_id(self):
        return self.canvas.layer_manager.active_layer_id

    def apply_translation(self):
        if self.canvas.transform_layer(self._active_layer_id(), dx=self.offset_x.value(), dy=self.offset_y.value()):
            self.offset_x.setValue(0); self.offset_y.setValue(0)

    def apply_rotation(self):
        if self.canvas.transform_layer(self._active_layer_id(), rotation=self.rotation.value()):
            self.rotation.setValue(0)

    def apply_scale(self):
        if self.canvas.transform_layer(self._active_layer_id(), scale=self.scale.value() / 100.0):
            self.scale.setValue(100)
