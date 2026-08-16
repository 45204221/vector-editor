"""Bridge selected editor geometry into the engine laboratory's 3D mesh input."""

from dataclasses import dataclass

from .geometry import GeometryCache, PrimitiveTopology, _map_point


@dataclass(frozen=True)
class MeshSource:
    shape_id: str = ""
    contour: tuple = ()
    triangles: tuple = ()
    warning: str = ""

    @property
    def valid(self):
        return len(self.contour) >= 3 and len(self.triangles) >= 3


def selected_mesh_source(canvas):
    selected = canvas.get_selected_shapes()
    if len(selected) != 1:
        return MeshSource(warning="请选择一个闭合且带填充的二维图元")
    shape = selected[0]
    cache = GeometryCache()
    cache.sync_snapshot(canvas.create_render_snapshot())
    contour = ()
    triangles = ()
    for primitive in cache.primitives_for_shape(shape.id):
        if not primitive.visible:
            continue
        if primitive.topology == PrimitiveTopology.LINE_LOOP and not contour:
            contour = tuple(_map_point(point, primitive.transform)
                            for point in primitive.vertices)
        elif primitive.topology == PrimitiveTopology.TRIANGLE_FAN and not triangles:
            points = tuple(_map_point(point, primitive.transform)
                           for point in primitive.vertices)
            expanded = []
            for index in range(1, len(points) - 1):
                expanded.extend((points[0], points[index], points[index + 1]))
            triangles = tuple(expanded)
    if len(contour) < 3 or len(triangles) < 3:
        return MeshSource(shape.id, warning="当前图元缺少闭合轮廓或填充三角形")
    return MeshSource(shape.id, contour, triangles)
