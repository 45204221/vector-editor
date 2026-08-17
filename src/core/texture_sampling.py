"""Deterministic CPU reference for mip generation and texture sampling."""

from dataclasses import dataclass
import math


FILTERS = ("nearest", "bilinear", "trilinear")


@dataclass(frozen=True)
class MipLevel:
    width: int
    height: int
    rgba: bytes


@dataclass(frozen=True)
class TextureFootprint:
    major: float
    minor: float
    ratio: float
    isotropic_lod: float
    anisotropic_lod: float
    direction_u: float
    direction_v: float
    taps: int


def build_checker_texture(size=256):
    size = int(size)
    if size <= 0 or size > 2048:
        raise ValueError("texture size must be between 1 and 2048")
    output = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            checker = ((x // 4) + (y // 4)) & 1
            if x % 32 < 2 or y % 32 < 2:
                color = (255, 86, 42, 255)
            elif checker:
                color = (232, 238, 246, 255)
            else:
                color = (25, 38, 58, 255)
            offset = (y * size + x) * 4
            output[offset:offset + 4] = bytes(color)
    return bytes(output)


def generate_mipmaps(rgba, width, height):
    width, height, rgba = int(width), int(height), bytes(rgba)
    if width <= 0 or height <= 0 or width > 2048 or height > 2048:
        raise ValueError("texture dimensions must be between 1 and 2048")
    if len(rgba) != width * height * 4:
        raise ValueError("RGBA8 buffer size does not match dimensions")
    levels = [MipLevel(width, height, rgba)]
    while width > 1 or height > 1:
        source = levels[-1]
        next_width, next_height = max(1, (width + 1) // 2), max(1, (height + 1) // 2)
        output = bytearray(next_width * next_height * 4)
        for y in range(next_height):
            for x in range(next_width):
                for channel in range(4):
                    total = count = 0
                    for offset_y in range(2):
                        source_y = min(height - 1, y * 2 + offset_y)
                        for offset_x in range(2):
                            source_x = min(width - 1, x * 2 + offset_x)
                            total += source.rgba[(source_y * width + source_x) * 4 + channel]
                            count += 1
                    output[(y * next_width + x) * 4 + channel] = (
                        total + count // 2) // count
        width, height = next_width, next_height
        levels.append(MipLevel(width, height, bytes(output)))
    return tuple(levels)


def _coordinate(value, size, repeat):
    return value % size if repeat else max(0, min(size - 1, value))


def _texel(level, x, y, repeat):
    x, y = _coordinate(x, level.width, repeat), _coordinate(y, level.height, repeat)
    offset = (y * level.width + x) * 4
    return tuple(float(value) for value in level.rgba[offset:offset + 4])


def _sample_level(level, u, v, linear, repeat):
    if not math.isfinite(u) or not math.isfinite(v):
        raise ValueError("texture coordinates must be finite")
    x, y = u * level.width - 0.5, v * level.height - 0.5
    if not linear:
        return _texel(level, math.floor(x + 0.5), math.floor(y + 0.5), repeat)
    x0, y0 = math.floor(x), math.floor(y)
    tx, ty = x - x0, y - y0
    c00 = _texel(level, x0, y0, repeat)
    c10 = _texel(level, x0 + 1, y0, repeat)
    c01 = _texel(level, x0, y0 + 1, repeat)
    c11 = _texel(level, x0 + 1, y0 + 1, repeat)
    return tuple((c00[channel] + (c10[channel] - c00[channel]) * tx) * (1.0 - ty) +
                 (c01[channel] + (c11[channel] - c01[channel]) * tx) * ty
                 for channel in range(4))


def sample_mipmaps(levels, u, v, lod, filter="nearest", repeat=True):
    levels = tuple(levels)
    if not levels:
        raise ValueError("mip chain cannot be empty")
    if filter not in FILTERS:
        raise ValueError("filter must be nearest, bilinear or trilinear")
    if not math.isfinite(lod):
        raise ValueError("LOD must be finite")
    lod = max(0.0, min(len(levels) - 1.0, float(lod)))
    if filter != "trilinear":
        level = math.floor(lod + 0.5)
        values = _sample_level(levels[level], u, v, filter == "bilinear", repeat)
    else:
        first = math.floor(lod)
        second = min(first + 1, len(levels) - 1)
        blend = lod - first
        low = _sample_level(levels[first], u, v, True, repeat)
        high = _sample_level(levels[second], u, v, True, repeat)
        values = tuple(low[channel] + (high[channel] - low[channel]) * blend
                       for channel in range(4))
    return tuple(max(0, min(255, math.floor(value + 0.5))) for value in values)


def texture_footprint(width, height, dudx, dvdx, dudy, dvdy, max_taps=8):
    """Return the texel-space ellipse implied by a 2x2 UV Jacobian."""
    width, height, max_taps = int(width), int(height), int(max_taps)
    values = tuple(map(float, (dudx, dvdx, dudy, dvdy)))
    if width <= 0 or height <= 0:
        raise ValueError("texture dimensions must be positive")
    if max_taps not in (1, 2, 4, 8):
        raise ValueError("max_taps must be 1, 2, 4 or 8")
    if not all(math.isfinite(value) for value in values):
        raise ValueError("texture derivatives must be finite")
    dudx, dvdx, dudy, dvdy = values
    dx = (dudx * width, dvdx * height)
    dy = (dudy * width, dvdy * height)
    # Eigenvalues of J*J^T are the squared ellipse axis lengths.
    a = dx[0] * dx[0] + dy[0] * dy[0]
    b = dx[0] * dx[1] + dy[0] * dy[1]
    c = dx[1] * dx[1] + dy[1] * dy[1]
    root = math.sqrt(max(0.0, (a - c) * (a - c) + 4.0 * b * b))
    major = math.sqrt(max(0.0, 0.5 * (a + c + root)))
    minor = math.sqrt(max(0.0, 0.5 * (a + c - root)))
    if abs(b) > 1e-12:
        direction = (major * major - c, b)
    elif a >= c:
        direction = (1.0, 0.0)
    else:
        direction = (0.0, 1.0)
    length = math.hypot(*direction)
    direction = ((direction[0] / length, direction[1] / length)
                 if length > 1e-12 else (1.0, 0.0))
    major_lod_axis = max(1.0, major)
    minor_lod_axis = max(1.0, minor)
    ratio = max(1.0, major_lod_axis / minor_lod_axis)
    taps = min(max_taps, max(1, int(math.ceil(ratio - 1e-12))))
    return TextureFootprint(
        major, minor, ratio, math.log2(major_lod_axis),
        math.log2(minor_lod_axis), direction[0], direction[1], taps)


def sample_anisotropic(levels, u, v, dudx, dvdx, dudy, dvdy,
                       max_taps=8, repeat=True):
    """Approximate anisotropic filtering with trilinear taps on the major axis."""
    levels = tuple(levels)
    if not levels:
        raise ValueError("mip chain cannot be empty")
    footprint = texture_footprint(
        levels[0].width, levels[0].height, dudx, dvdx, dudy, dvdy, max_taps)
    span = max(0.0, footprint.major - max(1.0, footprint.minor))
    direction_u = footprint.direction_u / levels[0].width
    direction_v = footprint.direction_v / levels[0].height
    total = [0.0, 0.0, 0.0, 0.0]
    for index in range(footprint.taps):
        offset = ((index + 0.5) / footprint.taps - 0.5) * span
        color = sample_mipmaps(
            levels, u + direction_u * offset, v + direction_v * offset,
            footprint.anisotropic_lod, "trilinear", repeat)
        for channel in range(4):
            total[channel] += color[channel]
    color = tuple(max(0, min(255, math.floor(
        value / footprint.taps + 0.5))) for value in total)
    return color, footprint
