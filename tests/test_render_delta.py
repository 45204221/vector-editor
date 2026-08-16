import os
import sys
import unittest


SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from core.canvas import Canvas


class RenderDeltaTests(unittest.TestCase):
    def setUp(self):
        self.canvas = Canvas(500, 400)
        self.canvas.consume_render_delta(force_full=True)

    def test_add_and_remove_include_order_changes(self):
        shape = self.canvas.create_rectangle(20, 20, 40, 40)
        self.assertTrue(self.canvas.add_shape(shape))

        added = self.canvas.consume_render_delta()
        self.assertEqual([item["id"] for item in added.upserted_shapes], [shape.id])
        self.assertEqual(added.ordered_shape_ids, (shape.id,))
        self.assertFalse(added.full_sync)

        self.canvas.remove_shape(shape)
        removed = self.canvas.consume_render_delta()
        self.assertEqual(removed.removed_shape_ids, (shape.id,))
        self.assertEqual(removed.ordered_shape_ids, ())

    def test_consuming_delta_clears_pending_changes(self):
        shape = self.canvas.create_rectangle(20, 20, 40, 40)
        self.canvas.add_shape(shape)
        self.canvas.consume_render_delta()

        empty = self.canvas.consume_render_delta()
        self.assertEqual(empty.upserted_shapes, ())
        self.assertEqual(empty.removed_shape_ids, ())
        self.assertEqual(empty.ordered_shape_ids, ())

    def test_node_move_upserts_its_rerouted_connection(self):
        first = self.canvas.create_rectangle(20, 20, 40, 40)
        second = self.canvas.create_rectangle(300, 200, 40, 40)
        self.canvas.add_shape(first)
        self.canvas.add_shape(second)
        connection = self.canvas.create_connection(first, 1, second, 3)
        self.canvas.add_shape(connection)
        self.canvas.consume_render_delta(force_full=True)

        self.canvas.move_shapes([first], 10, 0)
        delta = self.canvas.consume_render_delta()
        by_id = {item["id"]: item for item in delta.upserted_shapes}

        self.assertIn(first.id, by_id)
        self.assertIn(connection.id, by_id)
        self.assertIn("routed_points", by_id[connection.id])


if __name__ == "__main__":
    unittest.main()
