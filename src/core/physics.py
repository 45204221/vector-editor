"""Qt 定时器驱动的简易刚体和弹簧约束。"""

from dataclasses import dataclass
from math import hypot
from typing import List

from PyQt5.QtCore import QPointF


@dataclass
class RigidBody:
    enabled: bool = False
    mass: float = 1.0
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    restitution: float = 0.8
    damping: float = 0.995
    is_static: bool = False
    def to_dict(self): return self.__dict__.copy()
    @classmethod
    def from_dict(cls, data): return cls(**{k: data.get(k, v) for k, v in cls().__dict__.items()})


@dataclass
class SpringConstraint:
    first_id: str
    second_id: str
    rest_length: float = 160.0
    stiffness: float = 20.0
    damping: float = 2.0

    def to_dict(self): return self.__dict__.copy()


class PhysicsWorld:
    def __init__(self, canvas):
        self.canvas = canvas
        self.running = False
        self.springs: List[SpringConstraint] = []

    def step(self, dt=1 / 60):
        shapes = [s for s in self.canvas.shapes if getattr(s, "rigid_body", None) and s.rigid_body.enabled]
        self._apply_springs(shapes, dt)
        for shape in shapes:
            body = shape.rigid_body
            if body.is_static or self.canvas.layer_manager.is_shape_locked(shape):
                continue
            self.canvas._translate_shape_world(shape, body.velocity_x * dt, body.velocity_y * dt)
            body.velocity_x *= body.damping
            body.velocity_y *= body.damping
            self._resolve_bounds(shape)

    def _resolve_bounds(self, shape):
        body, rect = shape.rigid_body, shape.bounding_rect()
        dx = dy = 0.0
        if rect.left() < 0: dx = -rect.left(); body.velocity_x = abs(body.velocity_x) * body.restitution
        elif rect.right() > self.canvas.width: dx = self.canvas.width - rect.right(); body.velocity_x = -abs(body.velocity_x) * body.restitution
        if rect.top() < 0: dy = -rect.top(); body.velocity_y = abs(body.velocity_y) * body.restitution
        elif rect.bottom() > self.canvas.height: dy = self.canvas.height - rect.bottom(); body.velocity_y = -abs(body.velocity_y) * body.restitution
        if dx or dy: self.canvas._translate_shape_world(shape, dx, dy)

    def _apply_springs(self, shapes, dt):
        by_id = {s.id: s for s in shapes}
        for spring in self.springs:
            first, second = by_id.get(spring.first_id), by_id.get(spring.second_id)
            if not first or not second: continue
            p1, p2 = first.bounding_rect().center(), second.bounding_rect().center()
            dx, dy = p2.x() - p1.x(), p2.y() - p1.y(); length = hypot(dx, dy)
            if not length: continue
            force = spring.stiffness * (length - spring.rest_length)
            for shape, sign in ((first, 1), (second, -1)):
                body = shape.rigid_body
                if not body.is_static:
                    body.velocity_x += sign * force * dx / length / max(body.mass, .01) * dt
                    body.velocity_y += sign * force * dy / length / max(body.mass, .01) * dt
