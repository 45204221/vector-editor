"""Exact Euclidean signed-distance transform reference (no Qt/OpenGL)."""

import math


_INF = 1.0e20


def _edt_1d(values):
    """Felzenszwalb/Huttenlocher squared EDT in linear time."""
    count = len(values)
    if not count:
        return ()
    finite = [index for index, value in enumerate(values) if value < _INF]
    if not finite:
        return tuple(_INF for _ in values)
    sites = [0] * count
    boundaries = [0.0] * (count + 1)
    k = 0
    sites[0] = finite[0]
    boundaries[0], boundaries[1] = -_INF, _INF
    for q in finite[1:]:
        while True:
            p = sites[k]
            crossing = ((values[q] + q * q) - (values[p] + p * p)) / (2.0 * (q - p))
            if crossing > boundaries[k] or k == 0:
                break
            k -= 1
        if crossing <= boundaries[k]:
            k = 0
        else:
            k += 1
        sites[k] = q
        boundaries[k], boundaries[k + 1] = crossing, _INF
    result = [0.0] * count
    k = 0
    for q in range(count):
        while boundaries[k + 1] < q:
            k += 1
        delta = q - sites[k]
        result[q] = delta * delta + values[sites[k]]
    return tuple(result)


def euclidean_distance_transform(features, width, height):
    """Return distance to the nearest truthy pixel for each pixel center."""
    width, height = int(width), int(height)
    mask = tuple(bool(value) for value in features)
    if width <= 0 or height <= 0 or len(mask) != width * height:
        raise ValueError("mask size must equal positive width * height")
    rows = []
    for y in range(height):
        rows.append(_edt_1d(tuple(0.0 if mask[y * width + x] else _INF
                                  for x in range(width))))
    squared = [0.0] * (width * height)
    for x in range(width):
        column = _edt_1d(tuple(rows[y][x] for y in range(height)))
        for y, value in enumerate(column):
            squared[y * width + x] = value
    return tuple(math.sqrt(value) if value < _INF else math.inf for value in squared)


def signed_distance_field(mask, width, height):
    """Positive inside, negative outside; boundary samples are one pixel apart."""
    values = tuple(bool(value) for value in mask)
    inside = euclidean_distance_transform(values, width, height)
    outside = euclidean_distance_transform((not value for value in values), width, height)
    return tuple(outside[index] - inside[index] for index in range(len(values)))


def encode_signed_distance_rgba8(distances, distance_range):
    """Encode signed scalar field to normalized RGBA8 for portable GL upload."""
    distance_range = float(distance_range)
    if not math.isfinite(distance_range) or distance_range <= 0.0:
        raise ValueError("distance_range must be finite and positive")
    output = bytearray()
    for distance in distances:
        normalized = max(0.0, min(1.0, 0.5 + float(distance) / (2.0 * distance_range)))
        encoded = int(round(normalized * 255.0))
        output.extend((encoded, encoded, encoded, 255))
    return bytes(output)
