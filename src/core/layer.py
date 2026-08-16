"""文档图层和图元 Z-order 管理。"""

from dataclasses import dataclass, asdict
from typing import List
from uuid import uuid4


@dataclass
class Layer:
    id: str
    name: str
    visible: bool = True
    locked: bool = False

    def to_dict(self): return asdict(self)


class LayerManager:
    def __init__(self):
        self.layers: List[Layer] = [Layer("content", "内容")]
        self.active_layer_id = "content"

    def ensure_layer(self, layer_id="content"):
        layer = self.get(layer_id)
        if not layer:
            layer = Layer(layer_id, layer_id)
            self.layers.append(layer)
        return layer

    def get(self, layer_id):
        return next((layer for layer in self.layers if layer.id == layer_id), None)

    def add(self, name):
        layer = Layer(str(uuid4()), name)
        self.layers.append(layer)
        return layer

    def set_active(self, layer_id):
        """设置绘制目标层；隐藏层和锁定层不能作为活动层。"""
        layer = self.get(layer_id)
        if layer and layer.visible and not layer.locked:
            self.active_layer_id = layer_id
            return True
        return False

    def remove(self, layer_id):
        if layer_id == "content": return False
        layer = self.get(layer_id)
        if layer:
            self.layers.remove(layer)
            if self.active_layer_id == layer_id:
                self.active_layer_id = "content"
            return True
        return False

    def ordered_shapes(self, shapes):
        position = {layer.id: i for i, layer in enumerate(self.layers)}
        return sorted((s for s in shapes if self.is_shape_visible(s)),
                      key=lambda s: (position.get(s.layer_id, 0), s.z_index))

    def is_shape_visible(self, shape):
        layer = self.get(getattr(shape, "layer_id", "content"))
        return shape.visible and (layer is None or layer.visible)

    def is_shape_locked(self, shape):
        layer = self.get(getattr(shape, "layer_id", "content"))
        return bool(layer and layer.locked)

    def to_dict(self): return [layer.to_dict() for layer in self.layers]

    def load(self, items):
        self.layers = [Layer(**item) for item in items] or [Layer("content", "内容")]
        self.ensure_layer("content")
        self.active_layer_id = "content"
