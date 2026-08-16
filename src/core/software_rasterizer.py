"""Python reference implementation for the M18 triangle rasterizer."""

from dataclasses import dataclass
import math
import time


@dataclass(frozen=True)
class RasterResult:
    width: int
    height: int
    color: bytes
    barycentric: bytes
    depth: bytes
    primitive_id: bytes
    input_triangles: int
    clipped_triangles: int
    rasterized_triangles: int
    covered_fragments: int
    depth_passed_fragments: int
    resolved_covered_pixels: int
    sample_count: int
    elapsed_ms: float
    backend: str = "Python reference"
    error: str = ""

    @property
    def buffer_bytes(self):
        return (len(self.color) + len(self.barycentric) + len(self.depth) +
                len(self.primitive_id))

    @property
    def native_working_set_bytes(self):
        # Three double RGB sample buffers + float Z + uint32 primitive,
        # plus the four resolved RGBA8 attachments returned to Python.
        return (self.width * self.height * self.sample_count * 80 +
                self.buffer_bytes)


def _byte(value):
    return int(math.floor(max(0.0, min(1.0, value)) * 255.0 + 0.5))


def _write(buffer, pixel, red, green, blue):
    offset = pixel * 4
    buffer[offset:offset + 4] = bytes((_byte(red), _byte(green), _byte(blue), 255))


def _edge(first, second, x, y):
    return ((x - first[0]) * (second[1] - first[1]) -
            (y - first[1]) * (second[0] - first[0]))


def _top_left(first, second):
    dx, dy = second[0] - first[0], second[1] - first[1]
    return dy < 0.0 or (abs(dy) <= 1e-10 and dx > 0.0)


def _accept(value, top_left):
    return value > 1e-10 or (value >= -1e-10 and top_left)


def _plane_distance(vertex, plane):
    x, y, z, w = vertex[:4]
    return (x + w, w - x, y + w, w - y, z + w, w - z)[plane]


def _interpolate(first, second, amount):
    return tuple(a + (b - a) * amount for a, b in zip(first, second))


def _clip_triangle(triangle):
    polygon = list(triangle)
    for plane in range(6):
        if not polygon:
            break
        output = []
        previous = polygon[-1]
        previous_distance = _plane_distance(previous, plane)
        previous_inside = previous_distance >= 0.0
        for current in polygon:
            current_distance = _plane_distance(current, plane)
            current_inside = current_distance >= 0.0
            if current_inside != previous_inside:
                denominator = previous_distance - current_distance
                amount = 0.0 if abs(denominator) <= 1e-15 else previous_distance / denominator
                output.append(_interpolate(previous, current, amount))
            if current_inside:
                output.append(current)
            previous, previous_distance = current, current_distance
            previous_inside = current_inside
        polygon = output
    return polygon


def software_rasterize(vertices, width, height, perspective_correct=True,
                       cull_back_faces=True, clip_volume=True, sample_count=1):
    width, height, sample_count = int(width), int(height), int(sample_count)
    if width <= 0 or height <= 0 or width > 512 or height > 512:
        raise ValueError("raster dimensions must be between 1 and 512")
    if sample_count not in (1, 4):
        raise ValueError("sample_count must be 1 or 4")
    vertices = tuple(tuple(map(float, vertex[:7])) for vertex in vertices)
    if len(vertices) % 3 or len(vertices) > 300000:
        raise ValueError("vertices must be a bounded triangle list")
    started = time.perf_counter()
    pixels = width * height
    background = (0.055, 0.075, 0.105)
    samples = pixels * sample_count
    sample_color = [background] * samples
    sample_bary = [background] * samples
    sample_depth_image = [background] * samples
    depth_buffer = [1.0] * samples
    sample_primitive = [0] * samples
    positions = ((0.375, 0.125), (0.875, 0.375),
                 (0.125, 0.625), (0.625, 0.875))
    rasterized = covered = passed = clipped = 0

    def rasterize_triangle(inputs, primitive):
        nonlocal rasterized, covered, passed
        screen = []
        for vertex in inputs:
            if not math.isfinite(vertex[3]) or vertex[3] <= 1e-9:
                return
            inverse = 1.0 / vertex[3]
            ndc_x, ndc_y, ndc_z = (vertex[index] * inverse for index in range(3))
            screen.append(((ndc_x * 0.5 + 0.5) * (width - 1),
                           (1.0 - (ndc_y * 0.5 + 0.5)) * (height - 1),
                           ndc_z * 0.5 + 0.5, inverse, *vertex[4:7]))
        area = _edge(screen[0], screen[1], screen[2][0], screen[2][1])
        if abs(area) <= 1e-12 or (cull_back_faces and area <= 0.0):
            return
        if area < 0.0:
            screen[1], screen[2] = screen[2], screen[1]
            area = -area
        rasterized += 1
        min_x = max(0, math.floor(min(point[0] for point in screen)))
        max_x = min(width - 1, math.ceil(max(point[0] for point in screen)))
        min_y = max(0, math.floor(min(point[1] for point in screen)))
        max_y = min(height - 1, math.ceil(max(point[1] for point in screen)))
        top_left = (_top_left(screen[1], screen[2]),
                    _top_left(screen[2], screen[0]),
                    _top_left(screen[0], screen[1]))
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                for sample_index in range(sample_count):
                    offset = (0.5, 0.5) if sample_count == 1 else positions[sample_index]
                    px, py = x + offset[0], y + offset[1]
                    edges = (_edge(screen[1], screen[2], px, py),
                             _edge(screen[2], screen[0], px, py),
                             _edge(screen[0], screen[1], px, py))
                    if not all(_accept(edges[index], top_left[index]) for index in range(3)):
                        continue
                    covered += 1
                    weights = tuple(value / area for value in edges)
                    z = sum(weights[index] * screen[index][2] for index in range(3))
                    pixel = y * width + x
                    sample = pixel * sample_count + sample_index
                    if z < 0.0 or z > 1.0 or z >= depth_buffer[sample]:
                        continue
                    attributes = weights
                    if perspective_correct:
                        denominator = sum(weights[index] * screen[index][3]
                                          for index in range(3))
                        if abs(denominator) <= 1e-12:
                            continue
                        attributes = tuple(weights[index] * screen[index][3] / denominator
                                           for index in range(3))
                    depth_buffer[sample] = z
                    passed += 1
                    sample_color[sample] = tuple(
                        sum(attributes[index] * screen[index][4 + channel]
                            for index in range(3)) for channel in range(3))
                    sample_bary[sample] = attributes
                    sample_depth_image[sample] = (z, z, z)
                    sample_primitive[sample] = primitive

    for start in range(0, len(vertices), 3):
        primitive = start // 3 + 1
        if clip_volume:
            polygon = _clip_triangle(vertices[start:start + 3])
            if len(polygon) < 3:
                continue
            clipped += len(polygon) - 2
            for index in range(1, len(polygon) - 1):
                rasterize_triangle((polygon[0], polygon[index], polygon[index + 1]),
                                   primitive)
        else:
            clipped += 1
            rasterize_triangle(vertices[start:start + 3], primitive)

    background_bytes = bytes((*map(_byte, background), 255))
    color = bytearray(background_bytes * pixels)
    barycentric = bytearray(background_bytes * pixels)
    depth_image = bytearray(background_bytes * pixels)
    primitive_id = bytearray(bytes((0, 0, 0, 255)) * pixels)
    resolved = 0
    for pixel in range(pixels):
        indices = range(pixel * sample_count, (pixel + 1) * sample_count)
        rgb = tuple(sum(sample_color[index][channel] for index in indices) / sample_count
                    for channel in range(3))
        indices = range(pixel * sample_count, (pixel + 1) * sample_count)
        bary = tuple(sum(sample_bary[index][channel] for index in indices) / sample_count
                     for channel in range(3))
        indices = range(pixel * sample_count, (pixel + 1) * sample_count)
        resolved_depth = tuple(
            sum(sample_depth_image[index][channel] for index in indices) / sample_count
            for channel in range(3))
        _write(color, pixel, *rgb)
        _write(barycentric, pixel, *bary)
        _write(depth_image, pixel, *resolved_depth)
        indices = range(pixel * sample_count, (pixel + 1) * sample_count)
        visible = [index for index in indices if sample_primitive[index]]
        primitive = (sample_primitive[min(visible, key=lambda index: depth_buffer[index])]
                     if visible else 0)
        offset = pixel * 4
        primitive_id[offset:offset + 4] = bytes(
            (primitive & 255, (primitive >> 8) & 255,
             (primitive >> 16) & 255, 255))
        resolved += bool(primitive)
    return RasterResult(width, height, bytes(color), bytes(barycentric),
                        bytes(depth_image), bytes(primitive_id),
                        len(vertices) // 3, clipped, rasterized, covered, passed,
                        resolved, sample_count,
                        (time.perf_counter() - started) * 1000.0)
