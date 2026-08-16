"""Pure-data contracts consumed by the M16.2 OpenGL lighting passes."""

from dataclasses import dataclass
import math
import struct


LIGHT_VERTEX_STRIDE = 8


@dataclass(frozen=True)
class LightFanFrame:
    key: tuple
    payload: bytes
    vertex_count: int


@dataclass(frozen=True)
class LightFanRange:
    first_vertex: int
    vertex_count: int


@dataclass(frozen=True)
class MultiLightFanFrame:
    key: tuple
    payload: bytes
    ranges: tuple
    vertex_count: int


def build_light_fan(snapshot):
    """Build a closed GL_TRIANGLE_FAN in scene coordinates."""
    if snapshot is None or len(snapshot.result.polygon) < 3:
        return LightFanFrame((), b"", 0)
    source = (snapshot.config.selected_source()
              if hasattr(snapshot.config, "selected_source") else snapshot.config)
    light = (float(source.x if hasattr(source, "x") else source.light_x),
             float(source.y if hasattr(source, "y") else source.light_y))
    polygon = tuple((float(x), float(y)) for x, y in snapshot.result.polygon)
    vertices = (light,) + polygon + (polygon[0],)
    values = tuple(component for point in vertices for component in point)
    payload = struct.pack("<{}f".format(len(values)), *values)
    return LightFanFrame((snapshot.source_revision, light, polygon), payload, len(vertices))


def build_multi_light_fan(snapshot):
    """Pack every visibility fan into one VBO with deterministic ranges."""
    values, ranges, key_parts = [], [], []
    first_vertex = 0
    visibilities = snapshot.light_visibilities or ()
    for visibility in visibilities:
        source = visibility.source
        polygon = tuple((float(x), float(y)) for x, y in visibility.result.polygon)
        if len(polygon) < 3:
            ranges.append(LightFanRange(first_vertex, 0))
            key_parts.append(((source.x, source.y), polygon))
            continue
        vertices = ((float(source.x), float(source.y)),) + polygon + (polygon[0],)
        values.extend(component for point in vertices for component in point)
        ranges.append(LightFanRange(first_vertex, len(vertices)))
        first_vertex += len(vertices)
        key_parts.append(((source.x, source.y), polygon))
    payload = struct.pack("<{}f".format(len(values)), *values) if values else b""
    return MultiLightFanFrame(
        (snapshot.source_revision, tuple(key_parts)), payload,
        tuple(ranges), first_vertex)


def device_light_parameters(transform, config):
    """Map the scene light and circular radius to the current Qt device space."""
    light_x = getattr(config, "light_x", getattr(config, "x", 0.0))
    light_y = getattr(config, "light_y", getattr(config, "y", 0.0))
    x = (transform.m11() * light_x + transform.m21() * light_y
         + transform.dx())
    y = (transform.m12() * light_x + transform.m22() * light_y
         + transform.dy())
    scale_x = math.hypot(transform.m11(), transform.m12())
    scale_y = math.hypot(transform.m21(), transform.m22())
    radius = config.radius * max(1e-6, (scale_x + scale_y) * 0.5)
    return float(x), float(y), float(radius)


def estimated_lighting_bytes(width, height):
    """Two single-sample RGBA8 viewport-sized attachments."""
    return max(1, int(width)) * max(1, int(height)) * 8
