"""Build the shared clip-space input used by the M18 CPU rasterizer."""

from PyQt5.QtGui import QVector3D, QVector4D

from .pipeline3d import pipeline_matrices


RECEIVER_VERTICES = ((-3.5, -1.35, -3.5, 0, 1, 0),
                     (3.5, -1.35, 3.5, 0, 1, 0),
                     (3.5, -1.35, -3.5, 0, 1, 0),
                     (-3.5, -1.35, -3.5, 0, 1, 0),
                     (-3.5, -1.35, 3.5, 0, 1, 0),
                     (3.5, -1.35, 3.5, 0, 1, 0))


def raster_input_vertices(mesh_vertices, config, width, height,
                          include_receiver=True):
    model, view, projection = pipeline_matrices(config, width / max(1.0, height))
    output = []

    def append(vertex, transform):
        position = QVector4D(vertex[0], vertex[1], vertex[2], 1.0)
        world = transform * position
        clip = projection * view * world
        normal = transform.mapVector(QVector3D(vertex[3], vertex[4], vertex[5]))
        if normal.lengthSquared() > 1e-12:
            normal.normalize()
        output.append((clip.x(), clip.y(), clip.z(), clip.w(),
                       normal.x() * 0.5 + 0.5,
                       normal.y() * 0.5 + 0.5,
                       normal.z() * 0.5 + 0.5))

    for vertex in mesh_vertices:
        append(vertex, model)
    if include_receiver:
        from PyQt5.QtGui import QMatrix4x4
        identity = QMatrix4x4()
        for vertex in RECEIVER_VERTICES:
            append(vertex, identity)
    return tuple(output)
