"""连接线路由后端。

接口只接收端点、障碍包围盒和画布尺寸，方便后续替换为 C++ 实现。
"""

from abc import ABC, abstractmethod
from heapq import heappop, heappush
from itertools import count
from typing import Iterable, List, Tuple

from PyQt5.QtCore import QPointF, QRectF, QLineF


class RoutingBackend(ABC):
    @abstractmethod
    def route(self, start: QPointF, end: QPointF, obstacles: Iterable[QRectF],
              width: float, height: float) -> List[QPointF]:
        pass


class GridAStarRouter(RoutingBackend):
    """直连/正交候选优先，网格 A* 作为复杂障碍兜底。"""

    def __init__(self, cell_size: int = 20):
        self.cell_size = max(5, int(cell_size))
        self.last_expanded_nodes = 0

    @staticmethod
    def _segment_hits_rect(first: QPointF, second: QPointF, rect: QRectF) -> bool:
        if rect.contains(first) or rect.contains(second):
            return True
        segment = QLineF(first, second)
        edges = (
            QLineF(rect.topLeft(), rect.topRight()),
            QLineF(rect.topRight(), rect.bottomRight()),
            QLineF(rect.bottomRight(), rect.bottomLeft()),
            QLineF(rect.bottomLeft(), rect.topLeft()),
        )
        return any(segment.intersect(edge, QPointF()) == QLineF.BoundedIntersection for edge in edges)

    def _path_clear(self, points, obstacles) -> bool:
        return not any(self._segment_hits_rect(a, b, rect)
                       for a, b in zip(points, points[1:]) for rect in obstacles)

    @staticmethod
    def _compress(points: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
        if len(points) < 3:
            return points
        result = [points[0]]
        for index in range(1, len(points) - 1):
            previous, current, following = result[-1], points[index], points[index + 1]
            if (current[0] - previous[0], current[1] - previous[1]) != (
                    following[0] - current[0], following[1] - current[1]):
                result.append(current)
        result.append(points[-1])
        return result

    def route(self, start, end, obstacles, width, height):
        obstacles = list(obstacles)
        self.last_expanded_nodes = 0
        if self._path_clear([start, end], obstacles):
            return [start, end]

        candidates = ([start, QPointF(end.x(), start.y()), end],
                      [start, QPointF(start.x(), end.y()), end])
        clear = [path for path in candidates if self._path_clear(path, obstacles)]
        if clear:
            return min(clear, key=lambda path: sum(abs(a.x() - b.x()) + abs(a.y() - b.y())
                                                   for a, b in zip(path, path[1:])))

        step = self.cell_size
        max_x, max_y = int(width // step), int(height // step)
        start_cell = (round(start.x() / step), round(start.y() / step))
        end_cell = (round(end.x() / step), round(end.y() / step))

        def blocked(cell):
            point = QPointF(cell[0] * step, cell[1] * step)
            return any(rect.contains(point) for rect in obstacles)

        queue = []
        order = count()
        heappush(queue, (0, next(order), start_cell))
        came_from = {start_cell: None}
        cost = {start_cell: 0}
        while queue:
            _, _, current = heappop(queue)
            self.last_expanded_nodes += 1
            if current == end_cell:
                break
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                neighbour = current[0] + dx, current[1] + dy
                if not (0 <= neighbour[0] <= max_x and 0 <= neighbour[1] <= max_y):
                    continue
                if neighbour not in (start_cell, end_cell) and blocked(neighbour):
                    continue
                new_cost = cost[current] + 1
                if neighbour not in cost or new_cost < cost[neighbour]:
                    cost[neighbour] = new_cost
                    priority = new_cost + abs(neighbour[0] - end_cell[0]) + abs(neighbour[1] - end_cell[1])
                    heappush(queue, (priority, next(order), neighbour))
                    came_from[neighbour] = current

        if end_cell not in came_from:
            return [start, end]
        cells, current = [], end_cell
        while current is not None:
            cells.append(current); current = came_from[current]
        cells.reverse()
        grid_points = [QPointF(x * step, y * step) for x, y in self._compress(cells)]
        result = [start] + grid_points + [end]
        return [point for index, point in enumerate(result)
                if index == 0 or point != result[index - 1]]
