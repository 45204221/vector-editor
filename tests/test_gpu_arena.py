import os
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt5.QtCore import QPointF
from PyQt5.QtWidgets import QApplication

from core.canvas import Canvas
from core.geometry import GeometryCache
from core.gpu_arena import GpuArena
from core.gpu_buffers import GpuUploadKind


APP = QApplication.instance() or QApplication([])


class GpuArenaTests(unittest.TestCase):
    def _build(self, shape_count=2):
        canvas = Canvas(800, 500)
        canvas.snap_to_grid = False
        shapes = [canvas.create_rectangle(20 + index * 100, 30, 60, 40)
                  for index in range(shape_count)]
        for shape in shapes:
            canvas.add_shape(shape)
        cache = GeometryCache()
        cache.sync_snapshot(canvas.create_render_snapshot())
        arena = GpuArena()
        arena.rebuild(cache)
        canvas.consume_render_delta(force_full=True)
        return canvas, shapes, cache, arena

    def _apply_canvas_delta(self, canvas, cache, arena):
        delta = canvas.consume_render_delta()
        cache.apply_delta(delta)
        arena.apply_delta(delta, cache)
        return delta

    def test_single_shape_move_reuses_slots_and_uploads_only_its_vertices(self):
        canvas, shapes, cache, arena = self._build(5)
        offsets = {key: allocation.first_vertex
                   for key, allocation in arena.allocations.items()}
        arena.mark_uploaded()

        canvas.move_shapes([shapes[2]], 5, 0)
        self._apply_canvas_delta(canvas, cache, arena)
        plan = arena.build_upload_plan()

        self.assertEqual(arena.last_shapes_touched, 1)
        self.assertEqual(arena.last_primitives_expanded, 2)
        self.assertEqual(offsets, {key: allocation.first_vertex
                                   for key, allocation in arena.allocations.items()})
        self.assertEqual(plan.kind, GpuUploadKind.PARTIAL)
        self.assertEqual(plan.byte_count, 3312)
        self.assertEqual(len(plan.ranges), 2)

    def test_removed_slots_are_reused_by_new_shape(self):
        canvas, shapes, cache, arena = self._build(2)
        capacity_before = arena.page.capacity_vertices
        arena.mark_uploaded()

        canvas.remove_shape(shapes[0])
        self._apply_canvas_delta(canvas, cache, arena)
        replacement = canvas.create_rectangle(300, 30, 60, 40)
        canvas.add_shape(replacement)
        self._apply_canvas_delta(canvas, cache, arena)

        self.assertEqual(arena.page.capacity_vertices, capacity_before)
        self.assertEqual({key[0] for key in arena.allocations},
                         {shapes[1].id, replacement.id})

    def test_capacity_growth_increments_allocation_generation(self):
        canvas = Canvas(800, 500); canvas.snap_to_grid = False
        polyline = canvas.create_polyline(
            [QPointF(20, 20), QPointF(40, 40), QPointF(60, 20)])
        canvas.add_shape(polyline)
        cache = GeometryCache(); cache.sync_snapshot(canvas.create_render_snapshot())
        arena = GpuArena(); arena.rebuild(cache); arena.mark_uploaded()
        canvas.consume_render_delta(force_full=True)
        key = (polyline.id, 0)
        previous_capacity = arena.allocations[key].capacity
        previous_generation = arena.allocations[key].generation

        polyline.points = [QPointF(20 + index * 10, 20 + index % 2 * 20)
                           for index in range(12)]
        canvas.update_world_state(emit=False, changed_shapes=[polyline])
        self._apply_canvas_delta(canvas, cache, arena)

        self.assertGreater(arena.allocations[key].capacity, previous_capacity)
        self.assertEqual(arena.allocations[key].generation, previous_generation + 1)

    def test_z_order_changes_commands_without_touching_allocations(self):
        canvas, shapes, cache, arena = self._build(2)
        offsets = {key: allocation.first_vertex
                   for key, allocation in arena.allocations.items()}
        arena.mark_uploaded()

        canvas.adjust_z_order([shapes[0]], 1)
        delta = self._apply_canvas_delta(canvas, cache, arena)
        frame = arena.build_frame(cache)

        self.assertFalse(delta.full_sync)
        self.assertEqual(delta.upserted_shapes, ())
        self.assertEqual(arena.last_shapes_touched, 0)
        self.assertEqual(arena.build_upload_plan().kind, GpuUploadKind.NONE)
        self.assertEqual(offsets, {key: allocation.first_vertex
                                   for key, allocation in arena.allocations.items()})
        first_drawn_shape = frame.batches[0].shape_ids[0]
        self.assertEqual(first_drawn_shape, shapes[1].id)

    def test_compaction_preserves_allocation_vertex_data(self):
        canvas, shapes, cache, arena = self._build(3)
        canvas.remove_shape(shapes[1])
        self._apply_canvas_delta(canvas, cache, arena)
        before = {key: arena.allocation_vertex_data(key)
                  for key in arena.allocations}

        arena.compact()

        after = {key: arena.allocation_vertex_data(key)
                 for key in arena.allocations}
        self.assertEqual(after, before)
        self.assertEqual(arena.compaction_count, 1)
        self.assertEqual(arena.fragmented_vertex_count, 0)
        self.assertEqual(arena.build_upload_plan().kind, GpuUploadKind.FULL)

    def test_hidden_layer_produces_no_draw_commands_and_can_be_restored(self):
        canvas, shapes, cache, arena = self._build(1)
        offsets = {key: allocation.first_vertex
                   for key, allocation in arena.allocations.items()}
        arena.mark_uploaded()

        canvas.set_layer_visibility("content", False)
        self._apply_canvas_delta(canvas, cache, arena)
        self.assertEqual(arena.build_frame(cache).batches, ())
        self.assertEqual(arena.build_upload_plan().kind, GpuUploadKind.NONE)
        self.assertEqual(offsets, {key: allocation.first_vertex
                                   for key, allocation in arena.allocations.items()})

        canvas.set_layer_visibility("content", True)
        self._apply_canvas_delta(canvas, cache, arena)
        self.assertTrue(arena.build_frame(cache).batches)
        self.assertEqual(arena.build_upload_plan().kind, GpuUploadKind.NONE)
        self.assertEqual(offsets, {key: allocation.first_vertex
                                   for key, allocation in arena.allocations.items()})

    def test_moving_node_updates_only_node_and_rerouted_connection(self):
        canvas = Canvas(800, 500); canvas.snap_to_grid = False
        first = canvas.create_rectangle(20, 30, 60, 40)
        second = canvas.create_rectangle(500, 300, 60, 40)
        canvas.add_shape(first); canvas.add_shape(second)
        connection = canvas.create_connection(first, 1, second, 3)
        canvas.add_shape(connection)
        cache = GeometryCache(); cache.sync_snapshot(canvas.create_render_snapshot())
        arena = GpuArena(); arena.rebuild(cache); arena.mark_uploaded()
        canvas.consume_render_delta(force_full=True)
        connection_before = {
            key: arena.allocation_vertex_data(key)
            for key in arena.allocations if key[0] == connection.id}

        canvas.move_shapes([first], 10, 0)
        self._apply_canvas_delta(canvas, cache, arena)
        connection_after = {
            key: arena.allocation_vertex_data(key)
            for key in arena.allocations if key[0] == connection.id}

        self.assertEqual(arena.last_shapes_touched, 2)
        self.assertEqual(arena.last_primitives_expanded, 4)
        self.assertNotEqual(connection_after, connection_before)
        self.assertEqual({key[0] for key in arena.allocations},
                         {first.id, second.id, connection.id})

    def test_undo_full_sync_rebuilds_equivalent_arena(self):
        canvas, shapes, cache, arena = self._build(1)
        original = {key: arena.allocation_vertex_data(key)
                    for key in arena.allocations}

        canvas.move_shapes([shapes[0]], 20, 0)
        self._apply_canvas_delta(canvas, cache, arena)
        canvas.undo()
        delta = self._apply_canvas_delta(canvas, cache, arena)

        restored = {key: arena.allocation_vertex_data(key)
                    for key in arena.allocations}
        self.assertTrue(delta.full_sync)
        self.assertEqual(restored, original)
        self.assertEqual(arena.allocation_count, 2)


if __name__ == "__main__":
    unittest.main()
