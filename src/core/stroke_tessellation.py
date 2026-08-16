"""Pure numeric polyline-to-triangle tessellation for OpenGL/C++ parity."""

import math


EPSILON = 1e-8


def _add(first, second):
    return first[0] + second[0], first[1] + second[1]


def _sub(first, second):
    return first[0] - second[0], first[1] - second[1]


def _mul(point, scalar):
    return point[0] * scalar, point[1] * scalar


def _length(point):
    return math.hypot(point[0], point[1])


def _cross(first, second):
    return first[0] * second[1] - first[1] * second[0]


def _line_intersection(first, first_direction, second, second_direction):
    denominator = _cross(first_direction, second_direction)
    if abs(denominator) <= EPSILON:
        return None
    offset = _sub(second, first)
    distance = _cross(offset, second_direction) / denominator
    return _add(first, _mul(first_direction, distance))


def _clean_points(points, closed):
    result = []
    for point in points:
        point = float(point[0]), float(point[1])
        if not result or _length(_sub(point, result[-1])) > EPSILON:
            result.append(point)
    if closed and len(result) > 1 and _length(_sub(result[0], result[-1])) <= EPSILON:
        result.pop()
    return result


def _triangle(result, first, second, third):
    if abs(_cross(_sub(second, first), _sub(third, first))) > EPSILON:
        result.extend((first, second, third))


def _round_fan(result, center, start, end, clockwise, segments):
    start_angle = math.atan2(start[1] - center[1], start[0] - center[0])
    end_angle = math.atan2(end[1] - center[1], end[0] - center[0])
    if clockwise:
        while end_angle >= start_angle:
            end_angle -= math.tau
    else:
        while end_angle <= start_angle:
            end_angle += math.tau
    sweep = end_angle - start_angle
    # atan2 implementations may land on opposite sides of an integer boundary
    # across CPython/MSVC. Bias by a tiny epsilon so Python/C++ choose one topology.
    steps = max(1, int(math.ceil(
        abs(sweep) / math.pi * max(2, segments) - 1e-12)))
    radius = _length(_sub(start, center))
    previous = start
    for step in range(1, steps + 1):
        angle = start_angle + sweep * step / steps
        current = (center[0] + math.cos(angle) * radius,
                   center[1] + math.sin(angle) * radius)
        _triangle(result, center, previous, current)
        previous = current


def tessellate_stroke(points, width, closed=False, join="miter", cap="butt",
                      miter_limit=4.0, round_segments=8):
    """Return a flat triangle-list of 2D points for one stroked path."""
    points = _clean_points(points, closed)
    width = max(0.0, float(width))
    if width <= EPSILON or len(points) < 2:
        return ()
    join = join if join in ("miter", "bevel", "round") else "miter"
    cap = cap if cap in ("butt", "square", "round") else "butt"
    half = width / 2.0
    segment_count = len(points) if closed else len(points) - 1
    segments = []
    for index in range(segment_count):
        first, second = points[index], points[(index + 1) % len(points)]
        offset = _sub(second, first)
        length = _length(offset)
        if length <= EPSILON:
            continue
        direction = _mul(offset, 1.0 / length)
        normal = -direction[1], direction[0]
        segments.append((index, first, second, direction, normal))
    if not segments:
        return ()

    result = []
    for segment_position, (_, first, second, direction, normal) in enumerate(segments):
        if not closed and cap == "square":
            if segment_position == 0:
                first = _sub(first, _mul(direction, half))
            if segment_position == len(segments) - 1:
                second = _add(second, _mul(direction, half))
        normal_offset = _mul(normal, half)
        first_left, first_right = _add(first, normal_offset), _sub(first, normal_offset)
        second_left, second_right = _add(second, normal_offset), _sub(second, normal_offset)
        _triangle(result, first_left, first_right, second_right)
        _triangle(result, first_left, second_right, second_left)

    join_indexes = range(len(points)) if closed else range(1, len(points) - 1)
    for index in join_indexes:
        previous = segments[(index - 1) % len(segments)]
        following = segments[index % len(segments)]
        center = points[index]
        previous_direction, previous_normal = previous[3], previous[4]
        next_direction, next_normal = following[3], following[4]
        turn = _cross(previous_direction, next_direction)
        if abs(turn) <= EPSILON:
            continue
        side = -1.0 if turn > 0 else 1.0
        outer_previous = _add(center, _mul(previous_normal, half * side))
        outer_next = _add(center, _mul(next_normal, half * side))
        if join == "round":
            _round_fan(result, center, outer_previous, outer_next,
                       clockwise=turn < 0, segments=round_segments)
            continue
        if join == "miter":
            miter = _line_intersection(
                outer_previous, previous_direction, outer_next, next_direction)
            if miter is not None and _length(_sub(miter, center)) <= miter_limit * half:
                _triangle(result, outer_previous, miter, outer_next)
                continue
        _triangle(result, outer_previous, center, outer_next)

    if not closed and cap == "round":
        first = points[0]
        first_normal = segments[0][4]
        _round_fan(result, first, _add(first, _mul(first_normal, half)),
                   _sub(first, _mul(first_normal, half)), clockwise=False,
                   segments=round_segments)
        last = points[-1]
        last_normal = segments[-1][4]
        _round_fan(result, last, _sub(last, _mul(last_normal, half)),
                   _add(last, _mul(last_normal, half)), clockwise=False,
                   segments=round_segments)
    return tuple(result)


def tessellate_segments(points, width, cap="butt", round_segments=8):
    """Tessellate independent point pairs without joining adjacent pairs."""
    result = []
    points = tuple(points)
    for index in range(0, len(points) - 1, 2):
        result.extend(tessellate_stroke(
            points[index:index + 2], width, cap=cap, round_segments=round_segments))
    return tuple(result)


def _coverage_triangle(result, first, second, third):
    if abs(_cross(_sub(second[:2], first[:2]), _sub(third[:2], first[:2]))) > EPSILON:
        result.extend((first, second, third))


def _coverage_quad(result, inner_first, inner_second, outer_second, outer_first):
    _coverage_triangle(result, (*inner_first, 1.0), (*inner_second, 1.0),
                       (*outer_second, 0.0))
    _coverage_triangle(result, (*inner_first, 1.0), (*outer_second, 0.0),
                       (*outer_first, 0.0))


def _arc_ring(result, center, inner_start, inner_end, clockwise, outer_radius,
              segments):
    start_angle = math.atan2(inner_start[1] - center[1], inner_start[0] - center[0])
    end_angle = math.atan2(inner_end[1] - center[1], inner_end[0] - center[0])
    if clockwise:
        while end_angle >= start_angle:
            end_angle -= math.tau
    else:
        while end_angle <= start_angle:
            end_angle += math.tau
    sweep = end_angle - start_angle
    steps = max(1, int(math.ceil(
        abs(sweep) / math.pi * max(2, segments) - 1e-12)))
    inner_radius = _length(_sub(inner_start, center))
    previous_inner, previous_outer = inner_start, (
        center[0] + math.cos(start_angle) * outer_radius,
        center[1] + math.sin(start_angle) * outer_radius)
    for step in range(1, steps + 1):
        angle = start_angle + sweep * step / steps
        current_inner = (center[0] + math.cos(angle) * inner_radius,
                         center[1] + math.sin(angle) * inner_radius)
        current_outer = (center[0] + math.cos(angle) * outer_radius,
                         center[1] + math.sin(angle) * outer_radius)
        _coverage_quad(result, previous_inner, current_inner,
                       current_outer, previous_outer)
        previous_inner, previous_outer = current_inner, current_outer


def tessellate_stroke_coverage(points, width, closed=False, join="miter", cap="butt",
                               antialias_width=1.0, miter_limit=4.0,
                               round_segments=8):
    """Return (x, y, coverage) triangles with a transparent outer AA fringe."""
    clean = _clean_points(points, closed)
    width = max(0.0, float(width))
    antialias_width = max(0.0, float(antialias_width))
    core = tessellate_stroke(clean, width, closed, join, cap,
                             miter_limit, round_segments)
    if not core:
        return ()
    if antialias_width <= EPSILON:
        return tuple((x, y, 1.0) for x, y in core)
    half, outer_half = width / 2.0, width / 2.0 + antialias_width
    segment_count = len(clean) if closed else len(clean) - 1
    segments = []
    for index in range(segment_count):
        first, second = clean[index], clean[(index + 1) % len(clean)]
        offset = _sub(second, first)
        length = _length(offset)
        if length <= EPSILON:
            continue
        direction = _mul(offset, 1.0 / length)
        segments.append((first, second, direction, (-direction[1], direction[0])))

    fringe = []
    for position, (first, second, direction, normal) in enumerate(segments):
        if not closed and cap == "square":
            if position == 0:
                first = _sub(first, _mul(direction, half))
            if position == len(segments) - 1:
                second = _add(second, _mul(direction, half))
        inner = _mul(normal, half)
        outer = _mul(normal, outer_half)
        _coverage_quad(fringe, _add(first, inner), _add(second, inner),
                       _add(second, outer), _add(first, outer))
        _coverage_quad(fringe, _sub(second, inner), _sub(first, inner),
                       _sub(first, outer), _sub(second, outer))

    join = join if join in ("miter", "bevel", "round") else "miter"
    join_indexes = range(len(clean)) if closed else range(1, len(clean) - 1)
    for index in join_indexes:
        previous = segments[(index - 1) % len(segments)]
        following = segments[index % len(segments)]
        center = clean[index]
        previous_direction, previous_normal = previous[2], previous[3]
        next_direction, next_normal = following[2], following[3]
        turn = _cross(previous_direction, next_direction)
        if abs(turn) <= EPSILON:
            continue
        side = -1.0 if turn > 0 else 1.0
        inner_previous = _add(center, _mul(previous_normal, half * side))
        inner_next = _add(center, _mul(next_normal, half * side))
        outer_previous = _add(center, _mul(previous_normal, outer_half * side))
        outer_next = _add(center, _mul(next_normal, outer_half * side))
        if join == "round":
            _arc_ring(fringe, center, inner_previous, inner_next,
                      clockwise=turn < 0, outer_radius=outer_half,
                      segments=round_segments)
            continue
        if join == "miter":
            inner_miter = _line_intersection(
                inner_previous, previous_direction, inner_next, next_direction)
            outer_miter = _line_intersection(
                outer_previous, previous_direction, outer_next, next_direction)
            if (inner_miter is not None and outer_miter is not None
                    and _length(_sub(inner_miter, center)) <= miter_limit * half
                    and _length(_sub(outer_miter, center)) <= miter_limit * outer_half):
                _coverage_quad(fringe, inner_previous, inner_miter,
                               outer_miter, outer_previous)
                _coverage_quad(fringe, inner_miter, inner_next,
                               outer_next, outer_miter)
                continue
        _coverage_quad(fringe, inner_previous, inner_next,
                       outer_next, outer_previous)

    if not closed:
        for is_start, (center, _, direction, normal) in (
                (True, segments[0]), (False, segments[-1])):
            if not is_start:
                center = segments[-1][1]
            if cap == "round":
                inner_start = (_add(center, _mul(normal, half)) if is_start
                               else _sub(center, _mul(normal, half)))
                inner_end = (_sub(center, _mul(normal, half)) if is_start
                             else _add(center, _mul(normal, half)))
                _arc_ring(fringe, center, inner_start, inner_end, clockwise=False,
                          outer_radius=outer_half, segments=round_segments)
            else:
                if cap == "square":
                    center = (_sub(center, _mul(direction, half)) if is_start
                              else _add(center, _mul(direction, half)))
                outward = _mul(direction, -antialias_width if is_start
                               else antialias_width)
                inner_left, inner_right = (_add(center, _mul(normal, half)),
                                           _sub(center, _mul(normal, half)))
                _coverage_quad(fringe, inner_right, inner_left,
                               _add(inner_left, outward), _add(inner_right, outward))
    return tuple(fringe) + tuple((x, y, 1.0) for x, y in core)


def tessellate_segments_coverage(points, width, cap="butt", antialias_width=1.0,
                                 round_segments=8):
    result = []
    points = tuple(points)
    for index in range(0, len(points) - 1, 2):
        result.extend(tessellate_stroke_coverage(
            points[index:index + 2], width, cap=cap,
            antialias_width=antialias_width, round_segments=round_segments))
    return tuple(result)
