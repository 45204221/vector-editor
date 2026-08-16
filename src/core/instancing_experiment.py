"""Pure configuration/data generation for the GPU instancing laboratory."""

from dataclasses import dataclass, replace
import math
import random
import struct

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPen, QPolygonF


SPRITE_MODES = (
    ("混合 Atlas", "mixed"),
    ("圆形", "circle"),
    ("菱形", "diamond"),
    ("星形", "star"),
)
SPRITE_VALUES = frozenset(value for _, value in SPRITE_MODES)
INSTANCE_FLOATS = 14
INSTANCE_STRIDE_BYTES = INSTANCE_FLOATS * 4
MAX_INSTANCES = 10_000
ATLAS_CELL_SIZE = 64
ATLAS_SIZE = (ATLAS_CELL_SIZE * 3, ATLAS_CELL_SIZE)


@dataclass(frozen=True)
class InstancingConfig:
    enabled: bool = False
    count: int = 500
    sprite_mode: str = "mixed"
    animate: bool = True
    seed: int = 1337

    def __post_init__(self):
        if not 1 <= int(self.count) <= MAX_INSTANCES:
            raise ValueError(f"instance count must be 1..{MAX_INSTANCES}")
        if self.sprite_mode not in SPRITE_VALUES:
            raise ValueError(f"unsupported sprite mode: {self.sprite_mode}")

    def changed(self, **changes):
        return replace(self, **changes)


@dataclass(frozen=True)
class InstanceData:
    payload: bytes
    count: int
    stride_bytes: int = INSTANCE_STRIDE_BYTES


def build_instance_data(config, canvas_width, canvas_height):
    if not isinstance(config, InstancingConfig):
        raise TypeError("config must be InstancingConfig")
    rng = random.Random(config.seed)
    values = []
    fixed_cell = {"circle": 0, "diamond": 1, "star": 2}.get(config.sprite_mode)
    palette = (
        (0.20, 0.72, 1.00, 0.88), (1.00, 0.34, 0.48, 0.88),
        (0.52, 0.91, 0.42, 0.88), (1.00, 0.76, 0.24, 0.88),
        (0.72, 0.44, 1.00, 0.88),
    )
    for index in range(config.count):
        cell = index % 3 if fixed_cell is None else fixed_cell
        base_x = rng.uniform(0.0, max(1.0, float(canvas_width)))
        base_y = rng.uniform(0.0, max(1.0, float(canvas_height)))
        speed = rng.uniform(18.0, 75.0)
        angle = rng.uniform(0.0, math.tau)
        velocity_x, velocity_y = math.cos(angle) * speed, math.sin(angle) * speed
        size = rng.uniform(14.0, 34.0)
        rotation = rng.uniform(0.0, math.tau)
        color = palette[index % len(palette)]
        u0 = cell / 3.0
        u1 = (cell + 1) / 3.0
        values.extend((base_x, base_y, velocity_x, velocity_y, size, rotation,
                       *color, u0, 0.0, u1, 1.0))
    payload = struct.pack("<{}f".format(len(values)), *values) if values else b""
    return InstanceData(payload, config.count)


def build_sprite_atlas():
    image = QImage(ATLAS_SIZE[0], ATLAS_SIZE[1], QImage.Format_RGBA8888)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor(255, 255, 255, 235), 3))
    painter.setBrush(QColor(255, 255, 255, 220))
    margin = 8
    painter.drawEllipse(margin, margin, 64 - margin * 2, 64 - margin * 2)
    diamond = QPolygonF((QPointF(96, 7), QPointF(121, 32),
                         QPointF(96, 57), QPointF(71, 32)))
    painter.drawPolygon(diamond)
    star_points = []
    center_x, center_y = 160.0, 32.0
    for index in range(10):
        angle = -math.pi / 2 + index * math.pi / 5
        radius = 26.0 if index % 2 == 0 else 12.0
        star_points.append(QPointF(center_x + math.cos(angle) * radius,
                                   center_y + math.sin(angle) * radius))
    painter.drawPolygon(QPolygonF(star_points))
    painter.end()
    return image

