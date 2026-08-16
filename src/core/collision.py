"""轻量 2D 碰撞系统：AABB、圆形，以及调试绘制所需状态。"""

from dataclasses import dataclass
from enum import Enum
from math import floor, hypot
from itertools import combinations
from typing import Dict, Iterable, Set, Tuple

from PyQt5.QtCore import QPointF, QRectF


class ColliderType(str, Enum):
    NONE = "none"
    AABB = "aabb"
    CIRCLE = "circle"


@dataclass
class Collider:
    type: ColliderType = ColliderType.AABB
    enabled: bool = True
    radius: float = 0.0

    def bounds(self, shape) -> QRectF:
        return shape.bounding_rect()

    def center(self, shape) -> QPointF:
        return self.bounds(shape).center()

    def effective_radius(self, shape) -> float:
        rect = self.bounds(shape)
        return self.radius if self.radius > 0 else min(rect.width(), rect.height()) / 2

    def to_dict(self):
        return {"type": self.type.value, "enabled": self.enabled, "radius": self.radius}

    @classmethod
    def from_dict(cls, data):
        return cls(ColliderType(data.get("type", "aabb")), data.get("enabled", True), data.get("radius", 0.0))


class CollisionSystem:
    """空间哈希 Broad Phase + AABB/圆形 Narrow Phase。"""

    def __init__(self, cell_size: float = 100.0):
        self.pairs: Set[Tuple[object, object]] = set()
        self.cell_size = cell_size
        self.last_candidate_pairs = 0
        self.last_narrow_phase_tests = 0
        self.last_bucket_count = 0
        self._buckets = {}
        self._shape_cells = {}
        self._shape_by_id = {}

    def _cells_for(self, shape):
        bounds = shape.collider.bounds(shape)
        return {(x, y)
                for x in range(floor(bounds.left() / self.cell_size), floor(bounds.right() / self.cell_size) + 1)
                for y in range(floor(bounds.top() / self.cell_size), floor(bounds.bottom() / self.cell_size) + 1)}

    @staticmethod
    def _eligible(shape):
        return (getattr(shape, "visible", True) and getattr(shape, "collider", None)
                and shape.collider.enabled and shape.collider.type != ColliderType.NONE)

    def _apply_pair(self, first, second):
        if self.intersects(first, second):
            self.pairs.add((first, second))
            first.is_colliding = second.is_colliding = True
            first.colliding_with.add(second)
            second.colliding_with.add(first)

    def update(self, shapes: Iterable[object]) -> Set[Tuple[object, object]]:
        candidates = [shape for shape in shapes if self._eligible(shape)]
        self.pairs.clear()
        self.last_candidate_pairs = 0
        self.last_narrow_phase_tests = 0
        for shape in candidates:
            shape.is_colliding = False
            shape.colliding_with = set()

        buckets: Dict[Tuple[int, int], list] = {}
        for shape in candidates:
            for cell in self._cells_for(shape):
                buckets.setdefault(cell, []).append(shape)
        self._buckets = buckets
        self._shape_cells = {shape.id: self._cells_for(shape) for shape in candidates}
        self._shape_by_id = {shape.id: shape for shape in candidates}
        self.last_bucket_count = len(buckets)

        broad_pairs = {}
        for bucket in buckets.values():
            for first, second in combinations(bucket, 2):
                key = tuple(sorted((first.id, second.id)))
                broad_pairs[key] = (first, second)
        self.last_candidate_pairs = len(broad_pairs)
        for first, second in broad_pairs.values():
            self.last_narrow_phase_tests += 1
            self._apply_pair(first, second)
        return self.pairs

    def update_incremental(self, shapes, changed_shapes):
        """仅重建变化图元所在的空间桶和相关碰撞对。"""
        candidates = [shape for shape in shapes if self._eligible(shape)]
        candidate_ids = {shape.id for shape in candidates}
        changed = [shape for shape in changed_shapes if shape.id in candidate_ids]
        if not self._shape_by_id or candidate_ids != set(self._shape_by_id):
            return self.update(candidates)
        changed_ids = {shape.id for shape in changed}
        if not changed_ids:
            return self.pairs

        for shape in changed:
            for cell in self._shape_cells.get(shape.id, set()):
                bucket = self._buckets.get(cell, [])
                if shape in bucket:
                    bucket.remove(shape)
                if not bucket:
                    self._buckets.pop(cell, None)
            cells = self._cells_for(shape)
            self._shape_cells[shape.id] = cells
            for cell in cells:
                self._buckets.setdefault(cell, []).append(shape)

        remaining_pairs = {(first, second) for first, second in self.pairs
                           if first.id not in changed_ids and second.id not in changed_ids}
        self.pairs = remaining_pairs
        for shape in candidates:
            shape.is_colliding = False
            shape.colliding_with = set()
        for first, second in remaining_pairs:
            first.is_colliding = second.is_colliding = True
            first.colliding_with.add(second); second.colliding_with.add(first)

        broad_pairs = {}
        for shape in changed:
            for cell in self._shape_cells[shape.id]:
                for other in self._buckets.get(cell, []):
                    if other is shape:
                        continue
                    key = tuple(sorted((shape.id, other.id)))
                    broad_pairs[key] = (shape, other)
        self.last_candidate_pairs = len(broad_pairs)
        self.last_narrow_phase_tests = len(broad_pairs)
        self.last_bucket_count = len(self._buckets)
        for first, second in broad_pairs.values():
            self._apply_pair(first, second)
        return self.pairs

    def intersects(self, first, second) -> bool:
        a, b = first.collider, second.collider
        if not a.bounds(first).intersects(b.bounds(second)):
            return False
        if a.type == ColliderType.AABB and b.type == ColliderType.AABB:
            return True
        if a.type == ColliderType.CIRCLE and b.type == ColliderType.CIRCLE:
            return hypot(a.center(first).x() - b.center(second).x(),
                         a.center(first).y() - b.center(second).y()) <= a.effective_radius(first) + b.effective_radius(second)
        circle_shape, box_shape = (first, second) if a.type == ColliderType.CIRCLE else (second, first)
        circle = circle_shape.collider
        rect = box_shape.collider.bounds(box_shape)
        center = circle.center(circle_shape)
        nearest_x = max(rect.left(), min(center.x(), rect.right()))
        nearest_y = max(rect.top(), min(center.y(), rect.bottom()))
        return hypot(center.x() - nearest_x, center.y() - nearest_y) <= circle.effective_radius(circle_shape)
