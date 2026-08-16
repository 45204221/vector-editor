"""Per-shape GPU slot arena with free-list allocation and dirty-range uploads."""

from dataclasses import dataclass
import struct
from typing import Dict, List, Optional, Tuple

from .geometry import Bounds, GeometryCache, PrimitiveTopology
from .gpu_buffers import (GpuCommandKind, GpuCommandRef, GpuDrawBatch,
                          GpuTextCommand, GpuTopology, GpuUploadKind,
                          GpuUploadPlan, GpuUploadRange, VERTEX_STRIDE_BYTES,
                          VERTEX_STRIDE_FLOATS, encode_gpu_primitive,
                          gpu_text_command)


AllocationKey = Tuple[str, int]


@dataclass
class GpuAllocation:
    key: AllocationKey
    shape_id: str
    primitive_index: int
    page_id: int
    first_vertex: int
    capacity: int
    vertex_count: int
    topology: GpuTopology
    render_pass: int
    line_width: float
    generation: int = 0


@dataclass
class GpuPage:
    page_id: int
    capacity_vertices: int
    vertices: List[float]
    free_ranges: List[Tuple[int, int]]
    dirty_ranges: List[Tuple[int, int]]


@dataclass(frozen=True)
class GpuArenaFrame:
    revision: int
    viewport: Optional[Bounds]
    batches: Tuple[GpuDrawBatch, ...]
    text_commands: Tuple[GpuTextCommand, ...]
    command_stream: Tuple[GpuCommandRef, ...]
    source_primitive_count: int
    visible_vertex_count: int


def _slot_capacity(required: int) -> int:
    capacity = 4
    while capacity < required:
        capacity *= 2
    return capacity


class GpuArena:
    """One-page arena today; page/allocation contracts are multi-page ready."""

    def __init__(self, initial_capacity: int = 64,
                 compaction_threshold: float = 0.45,
                 minimum_compaction_hole: int = 128):
        initial_capacity = max(4, _slot_capacity(initial_capacity))
        self.initial_capacity = initial_capacity
        self.compaction_threshold = float(compaction_threshold)
        self.minimum_compaction_hole = int(minimum_compaction_hole)
        self.allocations: Dict[AllocationKey, GpuAllocation] = {}
        self._shape_keys: Dict[str, List[AllocationKey]] = {}
        self.revision = -1
        self.layout_generation = 0
        self.compaction_count = 0
        self.last_shapes_touched = 0
        self.last_primitives_expanded = 0
        self.last_removed_shapes = 0
        self._requires_full_upload = True
        self.page = self._new_page()

    def _new_page(self) -> GpuPage:
        return GpuPage(0, self.initial_capacity,
                       [0.0] * (self.initial_capacity * VERTEX_STRIDE_FLOATS),
                       [(0, self.initial_capacity)], [])

    def clear(self) -> None:
        self.allocations.clear()
        self._shape_keys.clear()
        self.page = self._new_page()
        self.layout_generation += 1
        self._requires_full_upload = True

    def rebuild(self, cache: GeometryCache) -> None:
        self.clear()
        self.last_shapes_touched = 0
        self.last_primitives_expanded = 0
        self.last_removed_shapes = 0
        for shape_id in cache.ordered_shape_ids:
            self._update_shape(shape_id, cache)
        self.revision = cache.revision

    def apply_delta(self, delta, cache: GeometryCache) -> None:
        if delta.full_sync:
            self.rebuild(cache)
            return
        self.last_shapes_touched = 0
        self.last_primitives_expanded = 0
        self.last_removed_shapes = 0
        for shape_id in delta.removed_shape_ids:
            if self.remove_shape(shape_id):
                self.last_removed_shapes += 1
        upserted_ids = tuple(dict.fromkeys(shape["id"] for shape in delta.upserted_shapes))
        for shape_id in upserted_ids:
            self._update_shape(shape_id, cache)
        self.revision = cache.revision
        self.maybe_compact()

    def _update_shape(self, shape_id: str, cache: GeometryCache) -> None:
        primitives = cache.primitives_for_shape(shape_id)
        old_keys = set(self._shape_keys.get(shape_id, ()))
        new_keys = []
        self.last_shapes_touched += 1
        for primitive_index, primitive in enumerate(primitives):
            key = (shape_id, primitive_index)
            if primitive.topology == PrimitiveTopology.TEXT:
                if key in self.allocations:
                    self._release(key)
                continue
            topology, line_width, encoded = encode_gpu_primitive(primitive)
            self.last_primitives_expanded += 1
            vertex_count = len(encoded) // VERTEX_STRIDE_FLOATS
            if not vertex_count:
                if key in self.allocations:
                    self._release(key)
                continue
            allocation = self.allocations.get(key)
            if allocation is None or allocation.capacity < vertex_count:
                previous_generation = allocation.generation + 1 if allocation else 0
                if allocation is not None:
                    self._release(key)
                first_vertex, capacity = self._allocate(vertex_count)
                allocation = GpuAllocation(
                    key, shape_id, primitive_index, self.page.page_id,
                    first_vertex, capacity, vertex_count, topology,
                    primitive.render_pass, line_width, previous_generation)
                self.allocations[key] = allocation
            else:
                allocation.vertex_count = vertex_count
                allocation.topology = topology
                allocation.render_pass = primitive.render_pass
                allocation.line_width = line_width
            self._write(allocation.first_vertex, encoded)
            new_keys.append(key)
            old_keys.discard(key)
        for key in old_keys:
            self._release(key)
        self._shape_keys[shape_id] = new_keys

    def remove_shape(self, shape_id: str) -> bool:
        keys = tuple(self._shape_keys.pop(shape_id, ()))
        for key in keys:
            self._release(key)
        return bool(keys)

    def _allocate(self, required: int) -> Tuple[int, int]:
        capacity = _slot_capacity(required)
        while True:
            for index, (first, count) in enumerate(self.page.free_ranges):
                if count < capacity:
                    continue
                if count == capacity:
                    self.page.free_ranges.pop(index)
                else:
                    self.page.free_ranges[index] = (first + capacity, count - capacity)
                return first, capacity
            self._grow(capacity)

    def _grow(self, minimum_extra: int) -> None:
        previous = self.page.capacity_vertices
        capacity = previous
        while capacity - previous < minimum_extra:
            capacity *= 2
        self.page.vertices.extend(
            [0.0] * ((capacity - previous) * VERTEX_STRIDE_FLOATS))
        self.page.capacity_vertices = capacity
        self.page.free_ranges.append((previous, capacity - previous))
        self._merge_free_ranges()
        self.layout_generation += 1
        self._requires_full_upload = True

    def _release(self, key: AllocationKey) -> None:
        allocation = self.allocations.pop(key, None)
        if allocation is None:
            return
        self.page.free_ranges.append((allocation.first_vertex, allocation.capacity))
        self._merge_free_ranges()

    def _merge_free_ranges(self) -> None:
        merged = []
        for first, count in sorted(self.page.free_ranges):
            if not count:
                continue
            if merged and first <= merged[-1][0] + merged[-1][1]:
                previous_first, previous_count = merged[-1]
                end = max(previous_first + previous_count, first + count)
                merged[-1] = (previous_first, end - previous_first)
            else:
                merged.append((first, count))
        self.page.free_ranges = merged

    def _write(self, first_vertex: int, encoded: Tuple[float, ...]) -> None:
        first = first_vertex * VERTEX_STRIDE_FLOATS
        if tuple(self.page.vertices[first:first + len(encoded)]) == encoded:
            return
        self.page.vertices[first:first + len(encoded)] = encoded
        vertex_count = len(encoded) // VERTEX_STRIDE_FLOATS
        if vertex_count:
            self.page.dirty_ranges.append((first_vertex, vertex_count))

    def maybe_compact(self) -> bool:
        holes = self.fragmented_vertex_count
        if (holes < self.minimum_compaction_hole
                or self.fragmentation_ratio < self.compaction_threshold):
            return False
        self.compact()
        return True

    def compact(self) -> None:
        ordered = sorted(self.allocations.values(), key=lambda item: item.first_vertex)
        vertices = [0.0] * len(self.page.vertices)
        cursor = 0
        for allocation in ordered:
            source = allocation.first_vertex * VERTEX_STRIDE_FLOATS
            count = allocation.vertex_count * VERTEX_STRIDE_FLOATS
            target = cursor * VERTEX_STRIDE_FLOATS
            vertices[target:target + count] = self.page.vertices[source:source + count]
            allocation.first_vertex = cursor
            allocation.generation += 1
            cursor += allocation.capacity
        self.page.vertices = vertices
        self.page.free_ranges = ([(cursor, self.page.capacity_vertices - cursor)]
                                 if cursor < self.page.capacity_vertices else [])
        self.page.dirty_ranges.clear()
        self.layout_generation += 1
        self.compaction_count += 1
        self._requires_full_upload = True

    def build_frame(self, cache: GeometryCache,
                    viewport: Optional[Bounds] = None) -> GpuArenaFrame:
        batches = []
        text_commands = []
        command_stream = []
        source_count = visible_vertices = 0
        for shape_id, primitive_index, primitive in cache.primitive_items(viewport):
            source_count += 1
            if primitive.topology == PrimitiveTopology.TEXT:
                text_commands.append(gpu_text_command(primitive))
                command_stream.append(GpuCommandRef(GpuCommandKind.TEXT,
                                                    len(text_commands) - 1))
                continue
            allocation = self.allocations.get((shape_id, primitive_index))
            if allocation is None or allocation.vertex_count == 0:
                continue
            visible_vertices += allocation.vertex_count
            can_merge = bool(
                command_stream
                and command_stream[-1].kind == GpuCommandKind.BATCH
                and command_stream[-1].index == len(batches) - 1
                and batches[-1].render_pass == allocation.render_pass
                and batches[-1].topology == allocation.topology
                and batches[-1].line_width == allocation.line_width
                and batches[-1].first_vertex + batches[-1].vertex_count
                == allocation.first_vertex)
            if can_merge:
                previous = batches[-1]
                batches[-1] = GpuDrawBatch(
                    previous.render_pass, previous.topology, previous.first_vertex,
                    previous.vertex_count + allocation.vertex_count,
                    previous.line_width, previous.shape_ids + (shape_id,))
            else:
                batches.append(GpuDrawBatch(
                    allocation.render_pass, allocation.topology,
                    allocation.first_vertex, allocation.vertex_count,
                    allocation.line_width, (shape_id,)))
                command_stream.append(GpuCommandRef(GpuCommandKind.BATCH,
                                                    len(batches) - 1))
        return GpuArenaFrame(cache.revision, viewport, tuple(batches),
                             tuple(text_commands), tuple(command_stream),
                             source_count, visible_vertices)

    def build_upload_plan(self, force_full: bool = False) -> GpuUploadPlan:
        if force_full or self._requires_full_upload:
            if not self.allocations:
                return GpuUploadPlan(GpuUploadKind.NONE, (), 0)
            payload = self._vertex_bytes(0, self.page.capacity_vertices)
            return GpuUploadPlan(
                GpuUploadKind.FULL,
                (GpuUploadRange(0, self.page.capacity_vertices, 0, payload),),
                self.used_vertex_count,
            )
        ranges = self._merged_dirty_ranges()
        if not ranges:
            return GpuUploadPlan(GpuUploadKind.NONE, (), 0)
        changed = sum(count for _, count in ranges)
        if changed / max(1, self.page.capacity_vertices) >= 0.35:
            payload = self._vertex_bytes(0, self.page.capacity_vertices)
            return GpuUploadPlan(
                GpuUploadKind.FULL,
                (GpuUploadRange(0, self.page.capacity_vertices, 0, payload),), changed)
        updates = tuple(GpuUploadRange(first, count,
                                       first * VERTEX_STRIDE_BYTES,
                                       self._vertex_bytes(first, count))
                        for first, count in ranges)
        return GpuUploadPlan(GpuUploadKind.PARTIAL, updates, changed)

    def mark_uploaded(self) -> None:
        self.page.dirty_ranges.clear()
        self._requires_full_upload = False

    def _merged_dirty_ranges(self) -> Tuple[Tuple[int, int], ...]:
        merged = []
        for first, count in sorted(self.page.dirty_ranges):
            if merged and first <= merged[-1][0] + merged[-1][1]:
                previous_first, previous_count = merged[-1]
                end = max(previous_first + previous_count, first + count)
                merged[-1] = (previous_first, end - previous_first)
            else:
                merged.append((first, count))
        return tuple(merged)

    def _vertex_bytes(self, first_vertex: int, vertex_count: int) -> bytes:
        first = first_vertex * VERTEX_STRIDE_FLOATS
        last = (first_vertex + vertex_count) * VERTEX_STRIDE_FLOATS
        values = self.page.vertices[first:last]
        return struct.pack("<{}f".format(len(values)), *values) if values else b""

    def allocation_vertex_data(self, key: AllocationKey) -> Tuple[float, ...]:
        allocation = self.allocations[key]
        first = allocation.first_vertex * VERTEX_STRIDE_FLOATS
        last = first + allocation.vertex_count * VERTEX_STRIDE_FLOATS
        return tuple(self.page.vertices[first:last])

    @property
    def allocation_count(self) -> int:
        return len(self.allocations)

    @property
    def used_vertex_count(self) -> int:
        return sum(item.vertex_count for item in self.allocations.values())

    @property
    def reserved_vertex_count(self) -> int:
        return sum(item.capacity for item in self.allocations.values())

    @property
    def free_vertex_count(self) -> int:
        return sum(count for _, count in self.page.free_ranges)

    @property
    def fragmented_vertex_count(self) -> int:
        if not self.allocations:
            return 0
        used_end = max(item.first_vertex + item.capacity
                       for item in self.allocations.values())
        return sum(max(0, min(first + count, used_end) - first)
                   for first, count in self.page.free_ranges if first < used_end)

    @property
    def fragmentation_ratio(self) -> float:
        if not self.allocations:
            return 0.0
        used_end = max(item.first_vertex + item.capacity
                       for item in self.allocations.values())
        return self.fragmented_vertex_count / max(1, used_end)
