"""Runtime lighting configuration and visibility debug data for M16."""

from dataclasses import dataclass, replace
import time

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QColor, QBrush, QPainterPath, QPen

from .geometry import GeometryCache, PrimitiveTopology, _map_point
from .native_visibility import visibility_polygon


DEBUG_MODES = (
    ("最终光照（仅光源标记）", "final"),
    ("组合视图", "combined"), ("可见多边形", "polygon"),
    ("遮挡边", "segments"), ("最近命中射线", "rays"),
    ("命中点", "hits"),
)
MAX_SEGMENTS = 2000
MAX_LIGHTS = 8


@dataclass(frozen=True)
class LightSource:
    x: float
    y: float
    radius: float = 420.0
    intensity: float = 1.0
    color: str = "#FFD36A"

    def __post_init__(self):
        if self.radius <= 0:
            raise ValueError("light radius must be positive")
        if not 0.0 <= self.intensity <= 4.0:
            raise ValueError("intensity must be between 0 and 4")
        if not QColor(self.color).isValid():
            raise ValueError("invalid light color")

    def changed(self, **changes):
        return replace(self, **changes)


@dataclass(frozen=True)
class LightingConfig:
    enabled: bool = False
    light_x: float = 640.0
    light_y: float = 360.0
    radius: float = 420.0
    intensity: float = 1.0
    ambient: float = 0.22
    color: str = "#FFD36A"
    debug_mode: str = "combined"
    angle_epsilon: float = 1e-5
    use_native: bool = True
    gpu_lighting: bool = True
    extra_lights: tuple = ()
    selected_light: int = 0

    def __post_init__(self):
        if self.radius <= 0:
            raise ValueError("light radius must be positive")
        if not 0.0 <= self.intensity <= 4.0:
            raise ValueError("intensity must be between 0 and 4")
        if not 0.0 <= self.ambient <= 1.0:
            raise ValueError("ambient must be between 0 and 1")
        if self.debug_mode not in {value for _, value in DEBUG_MODES}:
            raise ValueError("unknown lighting debug mode")
        if self.angle_epsilon <= 0:
            raise ValueError("angle_epsilon must be positive")
        if len(self.extra_lights) >= MAX_LIGHTS:
            raise ValueError(f"at most {MAX_LIGHTS} lights are supported")
        if any(not isinstance(light, LightSource) for light in self.extra_lights):
            raise TypeError("extra_lights must contain LightSource values")
        if not 0 <= self.selected_light < len(self.light_sources()):
            raise ValueError("selected light index is out of range")

    def changed(self, **changes):
        return replace(self, **changes)

    def light_sources(self):
        primary = LightSource(self.light_x, self.light_y, self.radius,
                              self.intensity, self.color)
        return (primary,) + tuple(self.extra_lights)

    def selected_source(self):
        return self.light_sources()[self.selected_light]


@dataclass(frozen=True)
class LightVisibility:
    source: LightSource
    result: object


@dataclass(frozen=True)
class LightingSnapshot:
    config: LightingConfig
    segments: tuple
    result: object
    build_ms: float
    truncated: bool
    source_revision: int
    light_visibilities: tuple = ()


def _active_cache(canvas, backend):
    cache = getattr(backend, "cache", None)
    if isinstance(cache, GeometryCache) and cache.revision == canvas.render_revision:
        return cache
    cache = GeometryCache()
    cache.sync_snapshot(canvas.create_render_snapshot())
    return cache


def extract_occluder_segments(canvas, backend=None, max_segments=MAX_SEGMENTS):
    """Extract transformed closed-outline edges plus the finite canvas boundary."""
    cache = _active_cache(canvas, backend)
    segments = [
        ((0.0, 0.0), (float(canvas.width), 0.0)),
        ((float(canvas.width), 0.0), (float(canvas.width), float(canvas.height))),
        ((float(canvas.width), float(canvas.height)), (0.0, float(canvas.height))),
        ((0.0, float(canvas.height)), (0.0, 0.0)),
    ]
    truncated = False
    for _, _, primitive in cache.primitive_items():
        if primitive.topology != PrimitiveTopology.LINE_LOOP:
            continue
        points = tuple(_map_point(point, primitive.transform)
                       for point in primitive.vertices)
        if len(points) < 2:
            continue
        for first, second in zip(points, points[1:] + points[:1]):
            if len(segments) >= max_segments:
                truncated = True
                return tuple(segments), truncated
            if first != second:
                segments.append((first, second))
    return tuple(segments), truncated


def build_lighting_snapshot(canvas, backend, config):
    started = time.perf_counter()
    segments, truncated = extract_occluder_segments(canvas, backend)
    light_visibilities = tuple(
        LightVisibility(source, visibility_polygon(
            (source.x, source.y), segments,
            config.angle_epsilon, config.use_native))
        for source in config.light_sources())
    result = light_visibilities[config.selected_light].result
    return LightingSnapshot(config, segments, result,
                            (time.perf_counter() - started) * 1000.0,
                            truncated, canvas.render_revision, light_visibilities)


def rebind_lighting_snapshot(snapshot, config):
    """Reuse geometric results when only uniforms/debug selection changed."""
    sources = config.light_sources()
    if len(sources) != len(snapshot.light_visibilities):
        raise ValueError("light count changed; visibility must be rebuilt")
    visibilities = tuple(
        LightVisibility(source, previous.result)
        for source, previous in zip(sources, snapshot.light_visibilities))
    return LightingSnapshot(
        config, snapshot.segments, visibilities[config.selected_light].result,
        snapshot.build_ms, snapshot.truncated, snapshot.source_revision,
        visibilities)


def draw_lighting_debug(painter, snapshot):
    """Draw the algorithm's real world-space inputs and outputs."""
    if snapshot is None or not snapshot.config.enabled:
        return
    config, result = snapshot.config, snapshot.result
    source = config.selected_source()
    light = QPointF(source.x, source.y)
    mode = config.debug_mode
    painter.save()
    painter.setRenderHint(painter.Antialiasing)
    if mode in ("combined", "polygon") and len(result.polygon) >= 3:
        path = QPainterPath(QPointF(*result.polygon[0]))
        for point in result.polygon[1:]:
            path.lineTo(QPointF(*point))
        path.closeSubpath()
        color = QColor(source.color); color.setAlpha(58)
        painter.setPen(QPen(QColor(source.color), 1.5))
        painter.setBrush(QBrush(color))
        painter.drawPath(path)
    if mode in ("combined", "segments"):
        pen = QPen(QColor(238, 74, 96, 210), 1.4, Qt.DashLine)
        painter.setPen(pen); painter.setBrush(Qt.NoBrush)
        for first, second in snapshot.segments:
            painter.drawLine(QPointF(*first), QPointF(*second))
    if mode in ("combined", "rays"):
        painter.setPen(QPen(QColor(255, 183, 52, 90), 0.8))
        for ray in result.rays:
            painter.drawLine(light, QPointF(*ray.point))
    if mode in ("combined", "hits"):
        painter.setPen(Qt.NoPen); painter.setBrush(QColor(255, 79, 117, 220))
        for ray in result.rays:
            painter.drawEllipse(QPointF(*ray.point), 2.2, 2.2)
    painter.setPen(QPen(QColor(source.color), 1.5))
    painter.setBrush(QColor(255, 244, 185, 235))
    painter.drawEllipse(light, 7.0, 7.0)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(QColor(source.color), 1.0, Qt.DashLine))
    painter.drawEllipse(light, source.radius, source.radius)
    painter.restore()
