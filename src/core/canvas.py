"""画布核心类"""

from PyQt5.QtCore import QObject, pyqtSignal, QRectF, QPointF
from PyQt5.QtGui import QPen, QColor, QPainter, QTransform
from typing import List, Optional, Tuple, Dict, Any
from uuid import uuid4

from core.shape import (Shape, ShapeType, RectangleShape, EllipseShape, LineShape,
                          PolygonShape, PolylineShape,
                          DiamondShape, RoundedRectShape, ParallelogramShape,
                          ResistorShape, CapacitorShape, InductorShape,
                          GroundShape, BatteryShape, DiodeShape, OrgNodeShape,
                          ConnectionShape, TextShape)
from core.selection import SelectionManager, SelectionMode
from core.transform import TransformUtils
from core.serializer import Serializer, HistoryManager
from core.layer import LayerManager
from core.collision import CollisionSystem
from core.physics import PhysicsWorld, SpringConstraint
from core.routing import GridAStarRouter
from core.rendering import RenderDelta, RenderDirtyFlag, RenderSnapshot
from core.profiling import PerformanceProfiler
from PyQt5.QtCore import Qt

class Canvas(QObject):
    """画布类，管理所有图形和操作"""

    # 信号定义
    shape_added = pyqtSignal(object)                   # 图形添加
    shape_removed = pyqtSignal(object)                 # 图形移除
    shape_selected = pyqtSignal(object)                 # 图形选择
    canvas_changed = pyqtSignal()                      # 画布变化
    selection_changed = pyqtSignal()                   # 选择变化
    history_changed = pyqtSignal()                     # 历史变化
    render_invalidated = pyqtSignal(int)               # 渲染数据失效
    preview_changed = pyqtSignal()                     # 非文档绘制预览变化
    layers_changed = pyqtSignal()                      # 图层拓扑/状态变化（低频）

    def __init__(self, width: float = 2000, height: float = 1500):
        super().__init__()
        self.shapes: List[Shape] = []
        self.preview_shapes: List[Shape] = []
        self.selection_manager = SelectionManager()
        self.serializer = Serializer()
        self.grid_size = 10
        self.snap_to_grid = True
        self.show_grid = True
        self.width = width
        self.height = height
        self.layer_manager = LayerManager()
        self.collision_system = CollisionSystem()
        self.physics_world = PhysicsWorld(self)
        self.routing_backend = GridAStarRouter(cell_size=20)
        self.show_engine_debug = True
        self.profiler = PerformanceProfiler(capacity=120)
        self.history_manager = HistoryManager(max_history=100)
        self._history_transaction = None
        self._history_restoring = False
        self.render_revision = 0
        self._render_dirty_flags = RenderDirtyFlag.ALL
        self._render_dirty_shape_ids = set()
        self._render_removed_shape_ids = set()
        self._render_full_sync = True
        self.canvas_changed.connect(self._on_canvas_changed)
        self._reset_history()

    def _on_canvas_changed(self):
        if self._render_dirty_flags == RenderDirtyFlag.NONE:
            self.invalidate_render(RenderDirtyFlag.ALL)

    def invalidate_render(self, flags=RenderDirtyFlag.ALL, shape_ids=None,
                          removed_ids=None, full_sync=False):
        self.render_revision += 1
        self._render_dirty_flags |= flags
        if shape_ids:
            self._render_dirty_shape_ids.update(shape_ids)
        if removed_ids:
            self._render_removed_shape_ids.update(removed_ids)
            self._render_dirty_shape_ids.difference_update(removed_ids)
        if full_sync or (shape_ids is None and removed_ids is None and flags == RenderDirtyFlag.ALL):
            self._render_full_sync = True
        self.render_invalidated.emit(int(flags))

    def consume_render_dirty_flags(self):
        flags = self._render_dirty_flags
        self._render_dirty_flags = RenderDirtyFlag.NONE
        self._render_dirty_shape_ids.clear()
        self._render_removed_shape_ids.clear()
        self._render_full_sync = False
        return flags

    def _render_shape_data(self, shape):
        data = shape.to_dict()
        data["effective_visible"] = self.layer_manager.is_shape_visible(shape)
        if isinstance(shape, ConnectionShape):
            data["routed_points"] = tuple(
                (point.x(), point.y()) for point in shape.routed_points)
            data["endpoint_points"] = (
                (shape._cached_p1.x(), shape._cached_p1.y()),
                (shape._cached_p2.x(), shape._cached_p2.y()),
            )
        return data

    def create_render_snapshot(self) -> RenderSnapshot:
        """创建可跨 Python/C++ 边界的纯数据渲染快照。"""
        ordered = self.sorted_shapes()
        by_id = {shape.id: self._render_shape_data(shape) for shape in ordered}
        return RenderSnapshot(
            revision=self.render_revision,
            width=self.width,
            height=self.height,
            grid_size=self.grid_size,
            show_grid=self.show_grid,
            ordered_shape_ids=tuple(shape.id for shape in ordered),
            shapes=tuple(by_id[shape.id] for shape in ordered),
        )

    def consume_render_delta(self, force_full=False) -> RenderDelta:
        """取得并清空待同步增量；原生后端每帧最多调用一次。"""
        full_sync = force_full or self._render_full_sync
        ordered = self.sorted_shapes()
        by_id = {shape.id: shape for shape in self.shapes}
        if full_sync:
            upserted = tuple(self._render_shape_data(shape) for shape in ordered)
        else:
            upserted = tuple(self._render_shape_data(by_id[shape_id])
                             for shape_id in sorted(self._render_dirty_shape_ids)
                             if shape_id in by_id)
        include_order = full_sync or bool(self._render_dirty_flags & (RenderDirtyFlag.ORDER | RenderDirtyFlag.VISIBILITY))
        delta = RenderDelta(
            revision=self.render_revision,
            dirty_flags=int(self._render_dirty_flags),
            upserted_shapes=upserted,
            removed_shape_ids=tuple(sorted(self._render_removed_shape_ids)),
            ordered_shape_ids=tuple(shape.id for shape in ordered) if include_order else (),
            full_sync=full_sync,
        )
        self._render_dirty_flags = RenderDirtyFlag.NONE
        self._render_dirty_shape_ids.clear()
        self._render_removed_shape_ids.clear()
        self._render_full_sync = False
        return delta

    # ── 文档历史：存储纯数据快照，恢复后由画布重建派生状态 ──

    def _serialize_shapes(self) -> List[Dict[str, Any]]:
        for shape in self.shapes:
            if isinstance(shape, ConnectionShape):
                shape._source_index = self.shapes.index(shape.source_shape) if shape.source_shape in self.shapes else -1
                shape._target_index = self.shapes.index(shape.target_shape) if shape.target_shape in self.shapes else -1
        result = []
        for shape in self.shapes:
            data = shape.to_dict()
            data["selected"] = False  # 选择是临时 UI 状态，不进入文档历史
            result.append(data)
        return result

    def _capture_document_state(self) -> Dict[str, Any]:
        return {
            "shapes": self._serialize_shapes(),
            "layers": self.layer_manager.to_dict(),
            "springs": [spring.to_dict() for spring in self.physics_world.springs],
            "grid_size": self.grid_size,
            "snap_to_grid": self.snap_to_grid,
            "show_grid": self.show_grid,
        }

    def _restore_document_state(self, state: Dict[str, Any]) -> None:
        self._history_restoring = True
        try:
            self.clear_preview_shapes()
            self.shapes = [Shape.from_dict(data) for data in state.get("shapes", [])]
            self.layer_manager.load(state.get("layers", []))
            self.physics_world.springs = [SpringConstraint(**item) for item in state.get("springs", [])]
            self.grid_size = state.get("grid_size", 10)
            self.snap_to_grid = state.get("snap_to_grid", True)
            self.show_grid = state.get("show_grid", True)
            for shape in self.shapes:
                if isinstance(shape, ConnectionShape):
                    source_index, target_index = getattr(shape, "_source_index", -1), getattr(shape, "_target_index", -1)
                    shape.source_shape = self.shapes[source_index] if 0 <= source_index < len(self.shapes) else None
                    shape.target_shape = self.shapes[target_index] if 0 <= target_index < len(self.shapes) else None
                    shape.refresh()
            self.selection_manager.clear_selection()
            self.update_world_state(emit=False)
        finally:
            self._history_restoring = False
        self.layers_changed.emit()

    def _reset_history(self) -> None:
        self.history_manager.clear()
        self.history_manager.add_state(self._capture_document_state())
        self._history_transaction = None
        self.history_changed.emit()

    def begin_history_transaction(self, label: str = "编辑") -> None:
        if not self._history_restoring and self._history_transaction is None:
            self._history_transaction = (label, self._capture_document_state())

    def commit_history_transaction(self) -> bool:
        if self._history_restoring or self._history_transaction is None:
            return False
        _, before = self._history_transaction
        self._history_transaction = None
        after = self._capture_document_state()
        if before == after:
            return False
        changed = self.history_manager.add_state(after)
        if changed: self.history_changed.emit()
        return changed

    def record_history(self, label: str = "编辑") -> bool:
        if self._history_restoring or self._history_transaction is not None:
            return False
        changed = self.history_manager.add_state(self._capture_document_state())
        if changed: self.history_changed.emit()
        return changed

    def add_shape(self, shape: Shape, use_active_layer: bool = True) -> bool:
        """添加图形到画布"""
        # Shape IDs own GeometryCache/GpuArena slots. Never admit two document
        # objects with the same identity, even if an external caller cloned data.
        existing_ids = {item.id for item in self.shapes}
        while shape.id in existing_ids:
            shape.id = str(uuid4())
        bounds = shape.bounding_rect()
        if bounds.width() > self.width or bounds.height() > self.height:
            return False
        clamp_dx, clamp_dy = self._clamp_group_delta([shape], 0, 0)
        self._translate_shape_world(shape, clamp_dx, clamp_dy)
        if use_active_layer and shape.layer_id == "content":
            shape.layer_id = self.layer_manager.active_layer_id
        self.shapes.append(shape)
        new_layer = self.layer_manager.get(shape.layer_id) is None
        self.layer_manager.ensure_layer(shape.layer_id)
        shape.z_index = max((s.z_index for s in self.shapes if s.layer_id == shape.layer_id), default=-1) + 1
        self.update_world_state(emit=False, changed_shapes=[shape])
        self.invalidate_render(RenderDirtyFlag.ORDER, shape_ids=[shape.id])
        self.shape_added.emit(shape)
        self.canvas_changed.emit()
        if new_layer:
            self.layers_changed.emit()
        self.record_history("创建图元")
        return True

    # ── 工具预览：独立于文档/历史/碰撞/RenderDelta ──

    def add_preview_shape(self, shape: Shape) -> None:
        if shape not in self.preview_shapes:
            self.preview_shapes.append(shape)
        self.preview_changed.emit()

    def update_preview_shape(self, shape: Shape) -> None:
        if shape in self.preview_shapes:
            self.preview_changed.emit()

    def remove_preview_shape(self, shape: Shape) -> None:
        if shape in self.preview_shapes:
            self.preview_shapes.remove(shape)
            self.preview_changed.emit()

    def clear_preview_shapes(self) -> None:
        if self.preview_shapes:
            self.preview_shapes.clear()
            self.preview_changed.emit()

    def remove_shape(self, shape: Shape) -> None:
        """从画布移除图形"""
        if shape in self.shapes:
            removed_id = shape.id
            self.shapes.remove(shape)
            self.update_world_state(emit=False, changed_shapes=[shape])
            self.invalidate_render(RenderDirtyFlag.GEOMETRY | RenderDirtyFlag.ORDER,
                                   removed_ids=[removed_id])
            self.shape_removed.emit(shape)
            self.canvas_changed.emit()
            self.record_history("删除图元")

    def clear_canvas(self) -> None:
        """清空画布"""
        self.clear_preview_shapes()
        self.shapes.clear()
        self.selection_manager.clear_selection()
        self.physics_world.springs.clear()
        self.collision_system.pairs.clear()
        self.canvas_changed.emit()
        self.record_history("清空画布")

    def get_shapes(self) -> List[Shape]:
        """获取所有图形"""
        return self.shapes.copy()

    def get_selected_shapes(self) -> List[Shape]:
        """获取选中的图形"""
        return self.selection_manager.get_selected_shapes()

    def select_shape(self, shape: Shape) -> None:
        """选择图形"""
        self.selection_manager.clear_selection()
        self.selection_manager.add_shape(shape)
        self.invalidate_render(RenderDirtyFlag.DEBUG, shape_ids=[shape.id])
        self.selection_changed.emit()
        self.canvas_changed.emit()

    def toggle_selection(self, shape: Shape) -> None:
        """切换图形选择状态"""
        self.selection_manager.toggle_shape(shape)
        self.invalidate_render(RenderDirtyFlag.DEBUG, shape_ids=[shape.id])
        self.selection_changed.emit()
        self.canvas_changed.emit()

    def clear_selection(self) -> None:
        """清除选择"""
        selected_ids = [shape.id for shape in self.selection_manager.get_selected_shapes()]
        self.selection_manager.clear_selection()
        self.invalidate_render(RenderDirtyFlag.DEBUG, shape_ids=selected_ids)
        self.selection_changed.emit()
        self.canvas_changed.emit()

    def set_selection_mode(self, mode: SelectionMode) -> None:
        """设置选择模式"""
        self.selection_manager.set_selection_mode(mode)

    def start_box_selection(self, point: QPointF) -> None:
        """开始框选"""
        self.selection_manager.start_box_selection(point)

    def update_box_selection(self, point: QPointF) -> None:
        """更新框选"""
        self.selection_manager.update_box_selection(point)

    def end_box_selection(self) -> None:
        """结束框选"""
        self.selection_manager.end_box_selection()
        self.selection_changed.emit()
        self.canvas_changed.emit()

    def move_shapes(self, shapes: List[Shape], dx: float, dy: float) -> None:
        """移动图形"""
        shapes = [shape for shape in shapes if not self.layer_manager.is_shape_locked(shape)]
        dx, dy = self._clamp_group_delta(shapes, dx, dy)
        for shape in shapes:
            self._translate_shape_world(shape, dx, dy)
        self._refresh_connections()
        self.update_world_state(emit=False, changed_shapes=shapes)
        self.canvas_changed.emit()
        self.record_history("移动图元")

    def update_world_state(self, emit=True, changed_shapes=None,
                           update_collision=True, update_routing=True) -> None:
        """同步碰撞状态与连接线路由，是编辑和物理系统的统一入口。"""
        with self.profiler.measure("world_total"):
            ordered = self.layer_manager.ordered_shapes(self.shapes)
            if update_collision:
                with self.profiler.measure("collision"):
                    if changed_shapes is not None:
                        self.collision_system.update_incremental(ordered, changed_shapes)
                    else:
                        self.collision_system.update(ordered)
            expanded_nodes = 0
            if update_routing:
                with self.profiler.measure("routing"):
                    self._refresh_connections()
                    expanded_nodes = self._route_connections()
            changed_ids = [shape.id for shape in changed_shapes] if changed_shapes is not None else None
            if changed_ids is not None and update_routing:
                changed_ids.extend(shape.id for shape in self.shapes
                                   if isinstance(shape, ConnectionShape))
            self.invalidate_render(RenderDirtyFlag.GEOMETRY | RenderDirtyFlag.TRANSFORM | RenderDirtyFlag.DEBUG,
                                   shape_ids=changed_ids, full_sync=changed_shapes is None)
            if emit:
                self.canvas_changed.emit()
        collision = self.collision_system
        self.profiler.set_gauge("shape_count", len(self.shapes))
        self.profiler.set_gauge("collision_pairs", len(collision.pairs))
        self.profiler.set_gauge("collision_candidates", collision.last_candidate_pairs)
        self.profiler.set_gauge("collision_narrow_tests", collision.last_narrow_phase_tests)
        self.profiler.set_gauge("routing_expanded_nodes", expanded_nodes)

    def _route_connections(self):
        """通过可替换路由后端计算连接线路径。"""
        nodes = [s for s in self.shapes if not isinstance(s, ConnectionShape) and self.layer_manager.is_shape_visible(s)]
        expanded_nodes = 0
        for connection in (s for s in self.shapes if isinstance(s, ConnectionShape)):
            connection.refresh(); p1, p2 = connection._cached_p1, connection._cached_p2
            obstacles = [s.bounding_rect().adjusted(-12, -12, 12, 12) for s in nodes if s not in (connection.source_shape, connection.target_shape)]
            connection.routed_points = self.routing_backend.route(
                p1, p2, obstacles, self.width, self.height)
            expanded_nodes += self.routing_backend.last_expanded_nodes
        return expanded_nodes

    def sorted_shapes(self):
        return self.layer_manager.ordered_shapes(self.shapes)

    def physics_step(self):
        if self.physics_world.running:
            self.physics_world.step()
            self.update_world_state()

    def _refresh_connections(self):
        for shape in self.shapes:
            if isinstance(shape, ConnectionShape):
                shape.refresh()

    def _get_group_bounds(self, shapes) -> QRectF:
        """返回图元组的联合世界坐标包围盒。"""
        shapes = list(shapes)
        if not shapes:
            return QRectF()
        bounds = shapes[0].bounding_rect()
        for shape in shapes[1:]:
            bounds = bounds.united(shape.bounding_rect())
        return bounds

    def _clamp_group_delta(self, shapes, dx: float, dy: float) -> Tuple[float, float]:
        """将整组平移限制在画布内；异常的大尺寸组不再尝试移动。"""
        shapes = list(shapes)
        if not shapes:
            return 0.0, 0.0
        bounds = self._get_group_bounds(shapes)
        if bounds.width() > self.width or bounds.height() > self.height:
            return 0.0, 0.0
        target_x = max(0.0, min(self.width - bounds.width(), bounds.x() + dx))
        target_y = max(0.0, min(self.height - bounds.height(), bounds.y() + dy))
        return target_x - bounds.x(), target_y - bounds.y()

    def _restore_transforms(self, snapshots) -> None:
        for shape, transform in snapshots:
            shape.transform = QTransform(transform)

    def _translate_shape_world(self, shape, dx: float, dy: float) -> None:
        """以场景坐标平移，避免现有缩放矩阵把位移再次放大。"""
        if not dx and not dy:
            return
        transform = shape.transform
        shape.transform = QTransform(
            transform.m11(), transform.m12(), transform.m21(), transform.m22(),
            transform.dx() + dx, transform.dy() + dy,
        )

    def _keep_group_in_canvas(self, shapes, snapshots) -> bool:
        """变换后统一回推图元组；尺寸超过画布则回滚操作。"""
        bounds = self._get_group_bounds(shapes)
        if bounds.width() > self.width or bounds.height() > self.height:
            self._restore_transforms(snapshots)
            return False
        dx = -bounds.left() if bounds.left() < 0 else self.width - bounds.right() if bounds.right() > self.width else 0.0
        dy = -bounds.top() if bounds.top() < 0 else self.height - bounds.bottom() if bounds.bottom() > self.height else 0.0
        if dx or dy:
            for shape in shapes:
                self._translate_shape_world(shape, dx, dy)
        return True

    def _apply_scale_with_limit(self, shapes, sx: float, sy: float, center: QPointF) -> bool:
        """执行缩放；放大超出画布时自动限制到最大合法比例。"""
        snapshots = [(shape, QTransform(shape.transform)) for shape in shapes]

        def apply(factor: float):
            self._restore_transforms(snapshots)
            for shape in shapes:
                shape.scale(1 + (sx - 1) * factor, 1 + (sy - 1) * factor, center)
            return self._keep_group_in_canvas(shapes, snapshots)

        if apply(1.0):
            return True
        # 二分寻找从原尺寸到请求尺寸之间的最大合法缩放。
        self._restore_transforms(snapshots)
        if sx <= 1.0 and sy <= 1.0:
            return False
        low, high = 0.0, 1.0
        for _ in range(24):
            middle = (low + high) / 2
            if apply(middle):
                low = middle
            else:
                high = middle
        if low < 1e-5:
            self._restore_transforms(snapshots)
            return False
        return apply(low)

    def rotate_shapes(self, shapes: List[Shape], angle: float, center: QPointF) -> None:
        """旋转图形"""
        shapes = [shape for shape in shapes if not self.layer_manager.is_shape_locked(shape)]
        snapshots = [(shape, QTransform(shape.transform)) for shape in shapes]
        for shape in shapes:
            shape.rotate(angle, center)
        if not self._keep_group_in_canvas(shapes, snapshots):
            return
        self.update_world_state()
        self.record_history("旋转图元")

    def _rebuild_transform(self, shape, rotation: float, scale_x: float, scale_y: float) -> None:
        """重建变换矩阵：旋转+缩放围绕局部中心，世界中心不变"""
        wcx = shape.bounding_rect().center().x()
        wcy = shape.bounding_rect().center().y()
        if hasattr(shape, 'rect'):
            lcx = shape.rect.x() + shape.rect.width() / 2
            lcy = shape.rect.y() + shape.rect.height() / 2
        elif hasattr(shape, 'points') and shape.points:
            xs = [p.x() for p in shape.points]; ys = [p.y() for p in shape.points]
            lcx = (min(xs) + max(xs)) / 2; lcy = (min(ys) + max(ys)) / 2
        elif hasattr(shape, 'line'):
            lcx = (shape.line[0].x() + shape.line[1].x()) / 2
            lcy = (shape.line[0].y() + shape.line[1].y()) / 2
        else:
            return
        previous = QTransform(shape.transform)
        shape.transform = QTransform()
        shape.transform.translate(wcx, wcy)
        shape.transform.rotate(rotation)
        shape.transform.scale(scale_x, scale_y)
        shape.transform.translate(-lcx, -lcy)
        self._keep_group_in_canvas([shape], [(shape, previous)])

    def scale_shapes(self, shapes: List[Shape], sx: float, sy: float, center: QPointF) -> None:
        """缩放图形"""
        shapes = [shape for shape in shapes if not self.layer_manager.is_shape_locked(shape)]
        if not self._apply_scale_with_limit(shapes, sx, sy, center):
            return
        self.update_world_state()
        self.record_history("缩放图元")

    def flip_shapes_horizontal(self, shapes: List[Shape], center_x: float) -> None:
        """水平翻转图形"""
        for shape in shapes:
            shape.flip_horizontal(center_x)
        self.canvas_changed.emit()
        self.record_history("水平翻转")

    def flip_shapes_vertical(self, shapes: List[Shape], center_y: float) -> None:
        """垂直翻转图形"""
        for shape in shapes:
            shape.flip_vertical(center_y)
        self.canvas_changed.emit()
        self.record_history("垂直翻转")

    def copy_shapes(self, shapes: List[Shape]) -> List[Shape]:
        """复制图形"""
        copied_shapes = []
        for shape in shapes:
            # 创建深拷贝
            shape_copy = Shape.from_dict(shape.to_dict(), preserve_id=False)
            # 偏移一点位置以区分原图形
            shape_copy.translate(10, 10)
            copied_shapes.append(shape_copy)
        return copied_shapes

    def paste_shapes(self, shapes: List[Shape]) -> None:
        """粘贴图形"""
        self.begin_history_transaction("粘贴图元")
        for shape in shapes:
            self.add_shape(shape, use_active_layer=False)
        self.commit_history_transaction()

    def delete_selected_shapes(self) -> None:
        """删除选中的图形"""
        selected = self.get_selected_shapes()
        for shape in selected:
            self.shapes.remove(shape)
        self.clear_selection()
        self.update_world_state()
        self.record_history("删除图元")

    def adjust_z_order(self, shapes, direction):
        """同层图元逐级前移/后移；direction 为 1 或 -1。"""
        changed = False
        for shape in shapes:
            peers = sorted([s for s in self.shapes if s.layer_id == shape.layer_id], key=lambda s: s.z_index)
            index = peers.index(shape)
            target = index + direction
            if 0 <= target < len(peers):
                shape.z_index, peers[target].z_index = peers[target].z_index, shape.z_index
                changed = True
        if changed:
            self.invalidate_render(RenderDirtyFlag.ORDER)
            self.canvas_changed.emit()
            self.record_history("调整图元层级")

    def reorder_layer(self, layer_id: str, delta: int) -> bool:
        """调整图层绘制顺序；不重建几何、碰撞或路由。"""
        layers = self.layer_manager.layers
        index = next((position for position, layer in enumerate(layers)
                      if layer.id == layer_id), None)
        target = index + delta if index is not None else -1
        if index is None or not 0 <= target < len(layers):
            return False
        layers[index], layers[target] = layers[target], layers[index]
        self.invalidate_render(RenderDirtyFlag.ORDER)
        self.layers_changed.emit()
        self.canvas_changed.emit()
        self.record_history("调整图层顺序")
        return True

    def move_selected_to_layer(self, layer_id):
        self.layer_manager.ensure_layer(layer_id)
        for shape in self.get_selected_shapes(): shape.layer_id = layer_id
        for index, shape in enumerate([s for s in self.shapes if s.layer_id == layer_id]): shape.z_index = index
        self.update_world_state()
        self.layers_changed.emit()
        self.record_history("移动到图层")

    def set_layer_visibility(self, layer_id: str, visible: bool) -> bool:
        """统一修改图层可见性并同步编辑、碰撞、路由、渲染与历史状态。"""
        layer = self.layer_manager.get(layer_id)
        visible = bool(visible)
        if layer is None or layer.visible == visible:
            return False
        layer.visible = visible
        if not visible and self.layer_manager.active_layer_id == layer_id:
            fallback = next((candidate for candidate in self.layer_manager.layers
                             if candidate.id != layer_id and candidate.visible
                             and not candidate.locked), None)
            if fallback is not None:
                self.layer_manager.active_layer_id = fallback.id
        affected = [shape for shape in self.shapes if shape.layer_id == layer_id]
        self.update_world_state(emit=False, changed_shapes=affected)
        self.invalidate_render(RenderDirtyFlag.VISIBILITY,
                               shape_ids=[shape.id for shape in affected])
        self.layers_changed.emit()
        self.canvas_changed.emit()
        self.record_history("显示或隐藏图层")
        return True

    def transform_layer(self, layer_id: str, dx: float = 0, dy: float = 0,
                        rotation: float = 0, scale: float = 1.0) -> bool:
        """整体变换一个图层中的可编辑图元；连接线随端点自动更新。"""
        layer = self.layer_manager.get(layer_id)
        if not layer or layer.locked:
            return False
        shapes = [shape for shape in self.shapes
                  if shape.layer_id == layer_id and not isinstance(shape, ConnectionShape)]
        if not shapes or (dx == 0 and dy == 0 and rotation == 0 and scale == 1.0):
            return False
        self.begin_history_transaction("变换图层")
        snapshots = [(shape, QTransform(shape.transform)) for shape in shapes]
        bounds = self._get_group_bounds(shapes)
        center = bounds.center()
        if dx or dy:
            safe_dx, safe_dy = self._clamp_group_delta(shapes, dx, dy)
            for shape in shapes:
                self._translate_shape_world(shape, safe_dx, safe_dy)
        if rotation:
            for shape in shapes:
                shape.rotate(rotation, center)
            if not self._keep_group_in_canvas(shapes, snapshots):
                self.commit_history_transaction()
                return False
        if scale != 1.0 and not self._apply_scale_with_limit(shapes, scale, scale, center):
            self.commit_history_transaction()
            return False
        self.update_world_state()
        return self.commit_history_transaction()

    # ── 对齐与分布 ──

    def _clamp_move(self, shape, dx, dy):
        """移动图形并钳制在画布内"""
        dx, dy = self._clamp_group_delta([shape], dx, dy)
        if dx == 0 and dy == 0:
            return
        self._translate_shape_world(shape, dx, dy)

    def align_left(self, shapes):
        if len(shapes) < 2: return
        ref = min(s.bounding_rect().left() for s in shapes)
        for s in shapes:
            self._clamp_move(s, ref - s.bounding_rect().left(), 0)
        self.canvas_changed.emit()
        self.record_history("左对齐")

    def align_right(self, shapes):
        if len(shapes) < 2: return
        ref = max(s.bounding_rect().right() for s in shapes)
        for s in shapes:
            self._clamp_move(s, ref - s.bounding_rect().right(), 0)
        self.canvas_changed.emit()
        self.record_history("右对齐")

    def align_top(self, shapes):
        if len(shapes) < 2: return
        ref = min(s.bounding_rect().top() for s in shapes)
        for s in shapes:
            self._clamp_move(s, 0, ref - s.bounding_rect().top())
        self.canvas_changed.emit()
        self.record_history("顶对齐")

    def align_bottom(self, shapes):
        if len(shapes) < 2: return
        ref = max(s.bounding_rect().bottom() for s in shapes)
        for s in shapes:
            self._clamp_move(s, 0, ref - s.bounding_rect().bottom())
        self.canvas_changed.emit()
        self.record_history("底对齐")

    def align_center_h(self, shapes):
        if len(shapes) < 2: return
        ref = sum(s.bounding_rect().center().x() for s in shapes) / len(shapes)
        for s in shapes:
            self._clamp_move(s, ref - s.bounding_rect().center().x(), 0)
        self.canvas_changed.emit()
        self.record_history("水平居中")

    def align_center_v(self, shapes):
        if len(shapes) < 2: return
        ref = sum(s.bounding_rect().center().y() for s in shapes) / len(shapes)
        for s in shapes:
            self._clamp_move(s, 0, ref - s.bounding_rect().center().y())
        self.canvas_changed.emit()
        self.record_history("垂直居中")

    def distribute_h(self, shapes):
        if len(shapes) < 2: return
        ordered = sorted(shapes, key=lambda s: s.bounding_rect().center().x())
        total_w = sum(s.bounding_rect().width() for s in ordered)
        leftmost = ordered[0].bounding_rect().left()
        rightmost = ordered[-1].bounding_rect().right()
        gap = max(0.0, (rightmost - leftmost - total_w) / max(len(ordered) - 1, 1))
        cur = leftmost
        for s in ordered:
            self._clamp_move(s, cur - s.bounding_rect().left(), 0)
            cur += s.bounding_rect().width() + gap
        self.canvas_changed.emit()
        self.record_history("水平分布")

    def distribute_v(self, shapes):
        if len(shapes) < 2: return
        ordered = sorted(shapes, key=lambda s: s.bounding_rect().center().y())
        total_h = sum(s.bounding_rect().height() for s in ordered)
        topmost = ordered[0].bounding_rect().top()
        bottommost = ordered[-1].bounding_rect().bottom()
        gap = max(0.0, (bottommost - topmost - total_h) / max(len(ordered) - 1, 1))
        cur = topmost
        for s in ordered:
            self._clamp_move(s, 0, cur - s.bounding_rect().top())
            cur += s.bounding_rect().height() + gap
        self.canvas_changed.emit()
        self.record_history("垂直分布")

    # ── 命中测试 ──

    def hit_test(self, point: QPointF) -> Optional[Shape]:
        """命中测试，返回点击的图形"""
        # 从后往前遍历，后绘制的图形在上层
        for shape in reversed(self.sorted_shapes()):
            if not self.layer_manager.is_shape_locked(shape) and shape.contains_point(shape.map_from_scene(point)):
                return shape
        return None

    def get_bounding_rect(self) -> QRectF:
        """获取画布的边界矩形"""
        if not self.shapes:
            return QRectF()

        first_shape = self.shapes[0]
        rect = first_shape.bounding_rect()

        for shape in self.shapes[1:]:
            shape_rect = shape.bounding_rect()
            rect = rect.united(shape_rect)

        return rect

    def save_to_file(self, file_path: str) -> bool:
        """保存画布到文件"""
        # 为连接线填充源/目标图形在列表中的索引
        for i, s in enumerate(self.shapes):
            if isinstance(s, ConnectionShape):
                try:
                    s._source_index = self.shapes.index(s.source_shape)
                except ValueError:
                    s._source_index = -1
                try:
                    s._target_index = self.shapes.index(s.target_shape)
                except ValueError:
                    s._target_index = -1
        return self.serializer.save_to_file(self.shapes, file_path, {
            "layers": self.layer_manager.to_dict(),
            "springs": [spring.to_dict() for spring in self.physics_world.springs],
        })

    def load_from_file(self, file_path: str) -> bool:
        """从文件加载画布"""
        shapes = self.serializer.load_from_file(file_path)
        if shapes:
            self.shapes = shapes
            self.layer_manager.load(getattr(self.serializer, "loaded_layers", []))
            self.layers_changed.emit()
            self.physics_world.springs = [SpringConstraint(**item) for item in getattr(self.serializer, "loaded_springs", [])]
            # 恢复连接线的源/目标图形引用
            for s in shapes:
                if isinstance(s, ConnectionShape):
                    si = getattr(s, '_source_index', -1)
                    ti = getattr(s, '_target_index', -1)
                    if 0 <= si < len(shapes):
                        s.source_shape = shapes[si]
                    if 0 <= ti < len(shapes):
                        s.target_shape = shapes[ti]
                    s.refresh()
            self.update_world_state(emit=False)
            self.clear_selection()
            self.canvas_changed.emit()
            self._reset_history()
            return True
        return False

    def export_to_svg(self, file_path: str) -> bool:
        """导出为 SVG——统一渲染通道，支持所有图形类型"""
        try:
            from PyQt5.QtSvg import QSvgGenerator
            from PyQt5.QtCore import QSize
            w, h = int(self.width), int(self.height)
            svg = QSvgGenerator()
            svg.setFileName(file_path)
            svg.setSize(QSize(w, h))
            painter = QPainter(svg)
            painter.fillRect(QRectF(0, 0, w, h), QColor(255, 255, 255))
            painter.setRenderHint(QPainter.Antialiasing)
            if self.show_grid:
                pen = QPen(QColor(220, 220, 220)); pen.setWidth(1)
                painter.setPen(pen)
                gs = self.grid_size
                for x in range(0, w + 1, gs): painter.drawLine(x, 0, x, h)
                for y in range(0, h + 1, gs): painter.drawLine(0, y, w, y)
            for shape in self.sorted_shapes():
                if self.layer_manager.is_shape_visible(shape):
                    shape.paint(painter, pass_type=1)
            for shape in self.sorted_shapes():
                if self.layer_manager.is_shape_visible(shape):
                    shape.paint(painter, pass_type=2)
            painter.end()
            return True
        except Exception as e:
            print(f"导出 SVG 失败: {e}")
            return False

    def export_to_png(self, file_path: str) -> bool:
        """导出为 PNG 位图"""
        from PyQt5.QtGui import QImage
        from PyQt5.QtCore import QRectF
        w, h = int(self.width), int(self.height)
        img = QImage(w, h, QImage.Format_ARGB32)
        img.fill(QColor(255, 255, 255))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing)
        # 网格
        if self.show_grid:
            pen = QPen(QColor(220, 220, 220))
            pen.setWidth(1); painter.setPen(pen)
            gs = self.grid_size
            for x in range(0, w + 1, gs): painter.drawLine(x, 0, x, h)
            for y in range(0, h + 1, gs): painter.drawLine(0, y, w, y)
        # 图形（两遍渲染：填充 → 边框）
        for shape in self.sorted_shapes():
            if self.layer_manager.is_shape_visible(shape):
                shape.paint(painter, pass_type=1)
        for shape in self.sorted_shapes():
            if self.layer_manager.is_shape_visible(shape):
                shape.paint(painter, pass_type=2)
        painter.end()
        return img.save(file_path, "PNG")

    def undo(self) -> bool:
        """恢复到上一条完整文档快照。"""
        state = self.history_manager.undo()
        if state is None:
            return False
        self._restore_document_state(state)
        self.selection_changed.emit()
        self.canvas_changed.emit()
        self.history_changed.emit()
        return True

    def can_undo(self) -> bool:
        return self.history_manager.can_undo()

    def redo(self) -> bool:
        """恢复到下一条完整文档快照。"""
        state = self.history_manager.redo()
        if state is None:
            return False
        self._restore_document_state(state)
        self.selection_changed.emit()
        self.canvas_changed.emit()
        self.history_changed.emit()
        return True

    def can_redo(self) -> bool:
        return self.history_manager.can_redo()

    # 网格相关方法
    def set_grid_size(self, size: int) -> None:
        """设置网格大小"""
        self.grid_size = size
        self.canvas_changed.emit()
        self.record_history("设置网格")

    def set_snap_to_grid(self, enabled: bool) -> None:
        """设置是否吸附到网格"""
        self.snap_to_grid = enabled
        self.canvas_changed.emit()
        self.record_history("设置网格吸附")

    def set_show_grid(self, show: bool) -> None:
        """设置是否显示网格"""
        self.show_grid = show
        self.canvas_changed.emit()
        self.record_history("显示网格")

    def snap_point_to_grid(self, point: QPointF) -> QPointF:
        """将点吸附到网格"""
        if self.snap_to_grid:
            return TransformUtils.snap_to_grid(point, self.grid_size)
        return point

    # 图形工厂方法
    def create_rectangle(self, x: float, y: float, width: float, height: float) -> RectangleShape:
        """创建矩形"""
        if self.snap_to_grid:
            x = round(x / self.grid_size) * self.grid_size
            y = round(y / self.grid_size) * self.grid_size
            width = round(width / self.grid_size) * self.grid_size
            height = round(height / self.grid_size) * self.grid_size

        return RectangleShape(x, y, width, height)

    def create_ellipse(self, x: float, y: float, width: float, height: float) -> EllipseShape:
        """创建椭圆"""
        if self.snap_to_grid:
            x = round(x / self.grid_size) * self.grid_size
            y = round(y / self.grid_size) * self.grid_size
            width = round(width / self.grid_size) * self.grid_size
            height = round(height / self.grid_size) * self.grid_size

        return EllipseShape(x, y, width, height)

    def create_line(self, x1: float, y1: float, x2: float, y2: float) -> LineShape:
        """创建直线"""
        if self.snap_to_grid:
            p1 = self.snap_point_to_grid(QPointF(x1, y1))
            p2 = self.snap_point_to_grid(QPointF(x2, y2))
            return LineShape(p1.x(), p1.y(), p2.x(), p2.y())
        return LineShape(x1, y1, x2, y2)

    def create_polygon(self, points: List[QPointF]) -> PolygonShape:
        """创建多边形"""
        if self.snap_to_grid:
            snapped_points = [self.snap_point_to_grid(p) for p in points]
            return PolygonShape(snapped_points)
        return PolygonShape(points)

    def create_polyline(self, points: List[QPointF]) -> PolylineShape:
        """创建折线"""
        if self.snap_to_grid:
            snapped_points = [self.snap_point_to_grid(p) for p in points]
            return PolylineShape(snapped_points)
        return PolylineShape(points)

    def create_diamond(self, x: float, y: float, width: float, height: float) -> DiamondShape:
        """创建菱形"""
        if self.snap_to_grid:
            x = round(x / self.grid_size) * self.grid_size
            y = round(y / self.grid_size) * self.grid_size
            width = round(width / self.grid_size) * self.grid_size
            height = round(height / self.grid_size) * self.grid_size
        return DiamondShape(x, y, width, height)

    def create_rounded_rect(self, x: float, y: float, width: float, height: float) -> RoundedRectShape:
        """创建圆角矩形"""
        if self.snap_to_grid:
            x = round(x / self.grid_size) * self.grid_size
            y = round(y / self.grid_size) * self.grid_size
            width = round(width / self.grid_size) * self.grid_size
            height = round(height / self.grid_size) * self.grid_size
        return RoundedRectShape(x, y, width, height)

    def create_parallelogram(self, x: float, y: float, width: float, height: float) -> ParallelogramShape:
        """创建平行四边形"""
        if self.snap_to_grid:
            x = round(x / self.grid_size) * self.grid_size
            y = round(y / self.grid_size) * self.grid_size
            width = round(width / self.grid_size) * self.grid_size
            height = round(height / self.grid_size) * self.grid_size
        return ParallelogramShape(x, y, width, height)

    def create_resistor(self, x: float, y: float, width: float, height: float) -> ResistorShape:
        if self.snap_to_grid:
            x = round(x / self.grid_size) * self.grid_size
            y = round(y / self.grid_size) * self.grid_size
            width = round(width / self.grid_size) * self.grid_size
            height = round(height / self.grid_size) * self.grid_size
        return ResistorShape(x, y, width, height)

    def create_capacitor(self, x: float, y: float, width: float, height: float) -> CapacitorShape:
        if self.snap_to_grid:
            x = round(x / self.grid_size) * self.grid_size
            y = round(y / self.grid_size) * self.grid_size
            width = round(width / self.grid_size) * self.grid_size
            height = round(height / self.grid_size) * self.grid_size
        return CapacitorShape(x, y, width, height)

    def create_inductor(self, x: float, y: float, width: float, height: float) -> InductorShape:
        if self.snap_to_grid:
            x = round(x / self.grid_size) * self.grid_size
            y = round(y / self.grid_size) * self.grid_size
            width = round(width / self.grid_size) * self.grid_size
            height = round(height / self.grid_size) * self.grid_size
        return InductorShape(x, y, width, height)

    def create_ground(self, x: float, y: float, width: float, height: float) -> GroundShape:
        if self.snap_to_grid:
            x = round(x / self.grid_size) * self.grid_size
            y = round(y / self.grid_size) * self.grid_size
            width = round(width / self.grid_size) * self.grid_size
            height = round(height / self.grid_size) * self.grid_size
        return GroundShape(x, y, width, height)

    def create_battery(self, x: float, y: float, width: float, height: float) -> BatteryShape:
        if self.snap_to_grid:
            x = round(x / self.grid_size) * self.grid_size
            y = round(y / self.grid_size) * self.grid_size
            width = round(width / self.grid_size) * self.grid_size
            height = round(height / self.grid_size) * self.grid_size
        return BatteryShape(x, y, width, height)

    def create_diode(self, x: float, y: float, width: float, height: float) -> DiodeShape:
        if self.snap_to_grid:
            x = round(x / self.grid_size) * self.grid_size
            y = round(y / self.grid_size) * self.grid_size
            width = round(width / self.grid_size) * self.grid_size
            height = round(height / self.grid_size) * self.grid_size
        return DiodeShape(x, y, width, height)

    def create_text(self, x: float, y: float, text: str) -> TextShape:
        """创建文字"""
        return TextShape(x, y, text)

    def create_connection(self, source_shape, source_anchor,
                           target_shape, target_anchor) -> ConnectionShape:
        """创建连接线"""
        return ConnectionShape(source_shape, source_anchor, target_shape, target_anchor)

    def create_org_node(self, x: float, y: float, width: float, height: float) -> OrgNodeShape:
        if self.snap_to_grid:
            x = round(x / self.grid_size) * self.grid_size
            y = round(y / self.grid_size) * self.grid_size
            width = round(width / self.grid_size) * self.grid_size
            height = round(height / self.grid_size) * self.grid_size
        return OrgNodeShape(x, y, width, height)


class CanvasRenderer:
    """画布渲染器"""

    def __init__(self, canvas: Canvas):
        self.canvas = canvas

    def render(self, painter: QPainter, rect: QRectF) -> None:
        """渲染画布"""
        # 绘制网格
        if self.canvas.show_grid:
            self._draw_grid(painter, rect)

        # 绘制所有图形
        for shape in self.canvas.shapes:
            if shape.visible:
                shape.paint(painter)

        # 绘制选择框
        self.canvas.selection_manager.draw_selection_box(painter)

    def _draw_grid(self, painter: QPainter, rect: QRectF) -> None:
        """绘制网格"""
        painter.save()
        painter.setPen(QPen(QColor("#E0E0E0"), 1))
        painter.setBrush(Qt.NoBrush)

        # 计算网格范围
        x1 = int(rect.left() / self.canvas.grid_size) * self.canvas.grid_size
        y1 = int(rect.top() / self.canvas.grid_size) * self.canvas.grid_size
        x2 = int(rect.right() / self.canvas.grid_size) * self.canvas.grid_size
        y2 = int(rect.bottom() / self.canvas.grid_size) * self.canvas.grid_size

        # 绘制垂直线
        for x in range(int(x1), int(x2) + 1, self.canvas.grid_size):
            painter.drawLine(x, rect.top(), x, rect.bottom())

        # 绘制水平线
        for y in range(int(y1), int(y2) + 1, self.canvas.grid_size):
            painter.drawLine(rect.left(), y, rect.right(), y)

        painter.restore()
