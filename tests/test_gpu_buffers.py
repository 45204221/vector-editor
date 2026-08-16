import os
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from core.canvas import Canvas
from core.geometry import GeometryCache
from core.gpu_buffers import (GpuBufferBuilder, GpuCommandKind, GpuTopology,
                              GpuUploadKind, VERTEX_STRIDE_BYTES, plan_gpu_upload)
from PyQt5.QtWidgets import QApplication


APP = QApplication.instance() or QApplication([])


class GpuBufferTests(unittest.TestCase):
    def _cache_for(self, canvas):
        cache = GeometryCache()
        cache.sync_snapshot(canvas.create_render_snapshot())
        return cache

    def test_rectangles_batch_into_stable_vertex_layout(self):
        canvas = Canvas(500, 400)
        canvas.add_shape(canvas.create_rectangle(10, 20, 40, 30))
        canvas.add_shape(canvas.create_rectangle(100, 20, 40, 30))

        frame = GpuBufferBuilder().build(self._cache_for(canvas))

        self.assertEqual(frame.vertex_count, 276)
        self.assertEqual(len(frame.vertex_bytes()), frame.vertex_count * VERTEX_STRIDE_BYTES)
        self.assertEqual([batch.topology for batch in frame.batches],
                         [GpuTopology.TRIANGLES, GpuTopology.TRIANGLES])
        self.assertEqual([batch.vertex_count for batch in frame.batches], [12, 264])

    def test_viewport_culls_primitives_using_world_bounds(self):
        canvas = Canvas(500, 400)
        first = canvas.create_rectangle(10, 20, 40, 30)
        second = canvas.create_rectangle(300, 200, 40, 30)
        canvas.add_shape(first)
        canvas.add_shape(second)
        cache = self._cache_for(canvas)

        frame = GpuBufferBuilder().build(cache, (0, 0, 100, 100))

        self.assertEqual(frame.source_primitive_count, 2)
        self.assertEqual(frame.vertex_count, 138)
        self.assertEqual({shape_id for batch in frame.batches for shape_id in batch.shape_ids},
                         {first.id})

    def test_text_preserves_command_order_and_breaks_vector_batch(self):
        canvas = Canvas(500, 400)
        first = canvas.create_rectangle(10, 20, 40, 30)
        text = canvas.create_text(80, 20, "GPU")
        second = canvas.create_rectangle(180, 20, 40, 30)
        canvas.add_shape(first)
        canvas.add_shape(text)
        canvas.add_shape(second)

        frame = GpuBufferBuilder().build(self._cache_for(canvas))
        stream_kinds = [command.kind for command in frame.command_stream]

        self.assertEqual(len(frame.text_commands), 1)
        self.assertIn(GpuCommandKind.TEXT, stream_kinds)
        text_position = stream_kinds.index(GpuCommandKind.TEXT)
        self.assertEqual(stream_kinds[text_position - 1:text_position + 2],
                         [GpuCommandKind.BATCH, GpuCommandKind.TEXT, GpuCommandKind.BATCH])

    def test_single_shape_move_plans_partial_vertex_upload(self):
        canvas = Canvas(500, 400)
        shapes = [canvas.create_rectangle(10 + index * 60, 20, 40, 30)
                  for index in range(5)]
        for shape in shapes:
            canvas.add_shape(shape)
        cache = self._cache_for(canvas)
        builder = GpuBufferBuilder()
        previous = builder.build(cache)
        canvas.consume_render_delta(force_full=True)

        canvas.move_shapes([shapes[2]], 5, 0)
        cache.apply_delta(canvas.consume_render_delta())
        current = builder.build(cache)
        plan = plan_gpu_upload(previous, current)

        self.assertEqual(plan.kind, GpuUploadKind.PARTIAL)
        self.assertEqual(plan.changed_vertex_count, 138)
        self.assertLess(plan.byte_count, len(current.vertex_bytes()))
        self.assertEqual(len(plan.ranges), 2)

    def test_vertex_count_change_requires_full_upload(self):
        canvas = Canvas(500, 400)
        canvas.add_shape(canvas.create_rectangle(10, 20, 40, 30))
        cache = self._cache_for(canvas)
        builder = GpuBufferBuilder()
        previous = builder.build(cache)
        canvas.consume_render_delta(force_full=True)

        canvas.add_shape(canvas.create_rectangle(100, 20, 40, 30))
        cache.apply_delta(canvas.consume_render_delta())
        current = builder.build(cache)
        plan = plan_gpu_upload(previous, current)

        self.assertEqual(plan.kind, GpuUploadKind.FULL)
        self.assertEqual(plan.byte_count, len(current.vertex_bytes()))

    def test_connection_stroke_and_arrow_share_triangle_batch(self):
        canvas = Canvas(500, 400)
        first = canvas.create_rectangle(20, 20, 40, 40)
        second = canvas.create_rectangle(300, 200, 40, 40)
        canvas.add_shape(first)
        canvas.add_shape(second)
        connection = canvas.create_connection(first, 1, second, 3)
        canvas.add_shape(connection)

        frame = GpuBufferBuilder().build(self._cache_for(canvas))
        connection_batches = [batch for batch in frame.batches
                              if connection.id in batch.shape_ids]

        self.assertEqual(len(connection_batches), 1)
        self.assertEqual(connection_batches[0].topology, GpuTopology.TRIANGLES)
        self.assertTrue(all(batch.topology == GpuTopology.TRIANGLES
                            for batch in frame.batches))


if __name__ == "__main__":
    unittest.main()
