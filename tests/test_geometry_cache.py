import os
import sys
import unittest


SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from core.canvas import Canvas
from core.geometry import GeometryCache, PrimitiveTopology


class GeometryCacheTests(unittest.TestCase):
    def setUp(self):
        self.canvas = Canvas(500, 400)

    def test_snapshot_compiles_fill_and_stroke_commands(self):
        rectangle = self.canvas.create_rectangle(10, 20, 80, 40)
        self.canvas.add_shape(rectangle)
        cache = GeometryCache()

        cache.sync_snapshot(self.canvas.create_render_snapshot())
        primitives = cache.primitives()

        self.assertEqual(cache.shape_count, 1)
        self.assertEqual([item.topology for item in primitives],
                         [PrimitiveTopology.TRIANGLE_FAN, PrimitiveTopology.LINE_LOOP])
        self.assertEqual([item.render_pass for item in primitives], [1, 2])

    def test_delta_recompiles_only_changed_shape(self):
        first = self.canvas.create_rectangle(10, 20, 80, 40)
        second = self.canvas.create_ellipse(200, 100, 60, 60)
        self.canvas.add_shape(first)
        self.canvas.add_shape(second)
        cache = GeometryCache()
        cache.sync_snapshot(self.canvas.create_render_snapshot())
        initial_count = cache.compiler.compile_count
        self.canvas.consume_render_delta(force_full=True)

        self.canvas.move_shapes([first], 5, 0)
        cache.apply_delta(self.canvas.consume_render_delta())

        self.assertEqual(cache.compiler.compile_count - initial_count, 1)
        self.assertEqual(cache.shape_count, 2)

    def test_delete_removes_cached_geometry(self):
        rectangle = self.canvas.create_rectangle(10, 20, 80, 40)
        self.canvas.add_shape(rectangle)
        cache = GeometryCache()
        cache.sync_snapshot(self.canvas.create_render_snapshot())
        self.canvas.consume_render_delta(force_full=True)

        self.canvas.remove_shape(rectangle)
        cache.apply_delta(self.canvas.consume_render_delta())

        self.assertEqual(cache.shape_count, 0)
        self.assertEqual(cache.primitives(), ())

    def test_connection_compiles_routed_polyline(self):
        first = self.canvas.create_rectangle(20, 20, 40, 40)
        second = self.canvas.create_rectangle(300, 200, 40, 40)
        self.canvas.add_shape(first)
        self.canvas.add_shape(second)
        connection = self.canvas.create_connection(first, 1, second, 3)
        self.canvas.add_shape(connection)
        cache = GeometryCache()
        cache.sync_snapshot(self.canvas.create_render_snapshot())

        connection_primitive = next(item for item in cache.primitives()
                                    if item.shape_id == connection.id)
        self.assertEqual(connection_primitive.topology, PrimitiveTopology.LINE_STRIP)
        self.assertGreaterEqual(len(connection_primitive.vertices), 2)


if __name__ == "__main__":
    unittest.main()
