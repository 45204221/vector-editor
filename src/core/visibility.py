"""Reference 2D visibility-polygon algorithm using ray/segment intersections."""

from dataclasses import dataclass
import math


PARALLEL_EPSILON = 1e-9
POINT_EPSILON = 1e-5


@dataclass(frozen=True)
class VisibilityRay:
    angle: float
    point: tuple
    distance: float
    segment_index: int


@dataclass(frozen=True)
class VisibilityResult:
    polygon: tuple
    rays: tuple
    segment_count: int
    intersection_tests: int
    backend: str = "Python reference"
    error: str = ""


def ray_segment_intersection(origin, direction, segment,
                             parallel_epsilon=PARALLEL_EPSILON):
    """Return (distance, point) for the forward ray hit, otherwise None."""
    ox, oy = map(float, origin)
    dx, dy = map(float, direction)
    (ax, ay), (bx, by) = segment
    sx, sy = float(bx) - float(ax), float(by) - float(ay)
    denominator = dx * sy - dy * sx
    if abs(denominator) <= parallel_epsilon:
        return None
    qx, qy = float(ax) - ox, float(ay) - oy
    distance = (qx * sy - qy * sx) / denominator
    along = (qx * dy - qy * dx) / denominator
    if distance < 0.0 or along < -parallel_epsilon or along > 1.0 + parallel_epsilon:
        return None
    return distance, (ox + distance * dx, oy + distance * dy)


def visibility_polygon(light, segments, angle_epsilon=1e-5):
    """Cast three rays around every segment endpoint and retain nearest hits."""
    light = (float(light[0]), float(light[1]))
    segments = tuple(((float(a[0]), float(a[1])),
                      (float(b[0]), float(b[1]))) for a, b in segments)
    if angle_epsilon <= 0:
        raise ValueError("angle_epsilon must be positive")
    angles = []
    for first, second in segments:
        for point in (first, second):
            base = math.atan2(point[1] - light[1], point[0] - light[0])
            angles.extend((base - angle_epsilon, base, base + angle_epsilon))
    hits = []
    tests = 0
    for angle in angles:
        direction = (math.cos(angle), math.sin(angle))
        nearest = None
        nearest_index = -1
        for index, segment in enumerate(segments):
            tests += 1
            hit = ray_segment_intersection(light, direction, segment)
            if hit is not None and (nearest is None or hit[0] < nearest[0]):
                nearest, nearest_index = hit, index
        if nearest is not None:
            hits.append(VisibilityRay(angle, nearest[1], nearest[0], nearest_index))
    hits.sort(key=lambda item: item.angle)
    filtered = []
    threshold_sq = POINT_EPSILON * POINT_EPSILON
    for hit in hits:
        if filtered:
            dx = hit.point[0] - filtered[-1].point[0]
            dy = hit.point[1] - filtered[-1].point[1]
            if dx * dx + dy * dy <= threshold_sq:
                continue
        filtered.append(hit)
    if len(filtered) > 1:
        dx = filtered[0].point[0] - filtered[-1].point[0]
        dy = filtered[0].point[1] - filtered[-1].point[1]
        if dx * dx + dy * dy <= threshold_sq:
            filtered.pop()
    return VisibilityResult(tuple(hit.point for hit in filtered), tuple(filtered),
                            len(segments), tests)
