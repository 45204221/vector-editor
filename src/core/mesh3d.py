"""Reference 2D-to-3D mesh generation for the M17 pipeline laboratory."""

from dataclasses import dataclass
import math
import struct


MESH_VERTEX_STRIDE = 24
MAX_MESH_VERTICES = 100000


@dataclass(frozen=True)
class Mesh3D:
    vertices: tuple
    backend: str = "Python reference"
    error: str = ""

    @property
    def vertex_count(self):
        return len(self.vertices)

    @property
    def triangle_count(self):
        return len(self.vertices) // 3

    @property
    def payload(self):
        values = tuple(value for vertex in self.vertices for value in vertex)
        return struct.pack("<{}f".format(len(values)), *values) if values else b""


def _normalize_inputs(contour, triangles):
    points = tuple((float(x), float(y)) for x, y in contour)
    faces = tuple((float(x), float(y)) for x, y in triangles)
    if len(points) < 3 or len(faces) < 3:
        raise ValueError("extrusion needs a closed contour and fill triangles")
    xs, ys = zip(*points)
    cx, cy = (min(xs) + max(xs)) * 0.5, (min(ys) + max(ys)) * 0.5
    scale = 2.0 / max(max(xs) - min(xs), max(ys) - min(ys), 1e-9)

    def convert(point):
        return ((point[0] - cx) * scale, -(point[1] - cy) * scale)

    return tuple(convert(point) for point in points), tuple(convert(point) for point in faces)


def _triangle(vertices, normal):
    return tuple((x, y, z, normal[0], normal[1], normal[2])
                 for x, y, z in vertices)


def extrude_mesh(contour, triangles, depth=0.7):
    depth = float(depth)
    if depth <= 0.0:
        raise ValueError("extrusion depth must be positive")
    contour, triangles = _normalize_inputs(contour, triangles)
    front_z, back_z = depth * 0.5, -depth * 0.5
    result = []
    for index in range(0, len(triangles) - 2, 3):
        first, second, third = triangles[index:index + 3]
        cross = ((second[0] - first[0]) * (third[1] - first[1])
                 - (second[1] - first[1]) * (third[0] - first[0]))
        if abs(cross) <= 1e-12:
            continue
        if cross < 0.0:
            second, third = third, second
        result.extend(_triangle(((first[0], first[1], front_z),
                                 (second[0], second[1], front_z),
                                 (third[0], third[1], front_z)), (0.0, 0.0, 1.0)))
        result.extend(_triangle(((first[0], first[1], back_z),
                                 (third[0], third[1], back_z),
                                 (second[0], second[1], back_z)), (0.0, 0.0, -1.0)))

    area = sum(first[0] * second[1] - second[0] * first[1]
               for first, second in zip(contour, contour[1:] + contour[:1])) * 0.5
    orientation = 1.0 if area >= 0.0 else -1.0
    for first, second in zip(contour, contour[1:] + contour[:1]):
        dx, dy = second[0] - first[0], second[1] - first[1]
        length = math.hypot(dx, dy)
        if length <= 1e-12:
            continue
        normal = (orientation * dy / length, -orientation * dx / length, 0.0)
        a = (first[0], first[1], front_z)
        b = (first[0], first[1], back_z)
        c = (second[0], second[1], back_z)
        d = (second[0], second[1], front_z)
        result.extend(_triangle((a, b, c), normal))
        result.extend(_triangle((a, c, d), normal))
    if len(result) > MAX_MESH_VERTICES:
        raise ValueError(f"mesh exceeds {MAX_MESH_VERTICES} vertices")
    return Mesh3D(tuple(result))


def cube_mesh():
    contour = ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0))
    triangles = (contour[0], contour[1], contour[2],
                 contour[0], contour[2], contour[3])
    return extrude_mesh(contour, triangles, 2.0)
