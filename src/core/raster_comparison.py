"""Metrics, heatmap and pixel probes for aligned CPU/GPU raster attachments."""

from dataclasses import dataclass
import math


BACKGROUND = (14, 19, 27)


@dataclass(frozen=True)
class RasterComparison:
    width: int
    height: int
    heatmap: bytes
    cpu_covered: int
    gpu_covered: int
    intersection: int
    union: int
    coverage_mismatch: int
    coverage_iou: float
    mae: float
    rmse: float
    max_error: int


def _covered(buffer, offset, tolerance=3):
    return any(abs(buffer[offset + channel] - BACKGROUND[channel]) > tolerance
               for channel in range(3))


def compare_rgba(cpu, gpu, width, height):
    expected = int(width) * int(height) * 4
    if len(cpu) != expected or len(gpu) != expected:
        raise ValueError("comparison buffers must be aligned RGBA8 images")
    heatmap = bytearray(expected)
    cpu_covered = gpu_covered = intersection = union = mismatch = 0
    total_absolute = total_squared = samples = max_error = 0
    for pixel in range(width * height):
        offset = pixel * 4
        cpu_hit, gpu_hit = _covered(cpu, offset), _covered(gpu, offset)
        cpu_covered += cpu_hit; gpu_covered += gpu_hit
        intersection += cpu_hit and gpu_hit; union += cpu_hit or gpu_hit
        mismatch += cpu_hit != gpu_hit
        differences = [abs(cpu[offset + channel] - gpu[offset + channel])
                       for channel in range(3)]
        if cpu_hit or gpu_hit:
            total_absolute += sum(differences)
            total_squared += sum(value * value for value in differences)
            samples += 3; max_error = max(max_error, *differences)
        if cpu_hit and not gpu_hit:
            color = (255, 30, 220)
        elif gpu_hit and not cpu_hit:
            color = (255, 210, 20)
        else:
            intensity = max(differences)
            color = (intensity, min(255, intensity * 2), 0)
        heatmap[offset:offset + 4] = bytes((*color, 255))
    return RasterComparison(
        width, height, bytes(heatmap), cpu_covered, gpu_covered,
        intersection, union, mismatch,
        intersection / union if union else 1.0,
        total_absolute / samples if samples else 0.0,
        math.sqrt(total_squared / samples) if samples else 0.0,
        max_error)


def pixel_probe(cpu_result, gpu_rgba, x, y, attachment="color"):
    x, y = int(x), int(y)
    if not 0 <= x < cpu_result.width or not 0 <= y < cpu_result.height:
        raise ValueError("probe coordinates are outside the attachment")
    offset = (y * cpu_result.width + x) * 4
    if attachment not in ("color", "depth"):
        raise ValueError("probe attachment must be color or depth")
    cpu_buffer = getattr(cpu_result, attachment)
    cpu = tuple(cpu_buffer[offset:offset + 4])
    gpu = tuple(gpu_rgba[offset:offset + 4])
    primitive = (cpu_result.primitive_id[offset] |
                 cpu_result.primitive_id[offset + 1] << 8 |
                 cpu_result.primitive_id[offset + 2] << 16)
    return {
        "x": x, "y": y, "cpu_rgba": cpu, "gpu_rgba": gpu,
        "absolute_rgb": tuple(abs(cpu[channel] - gpu[channel])
                              for channel in range(3)),
        "cpu_covered": _covered(cpu_buffer, offset),
        "gpu_covered": _covered(gpu_rgba, offset),
        "triangle_id": primitive - 1 if primitive else None,
        "barycentric": tuple(value / 255.0 for value in
                             cpu_result.barycentric[offset:offset + 3]),
        "depth": cpu_result.depth[offset] / 255.0,
    }
