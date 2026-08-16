"""Pure-data contracts for the offscreen render/picking laboratory."""

from dataclasses import dataclass


PICKING_MODES = (
    ("CPU（稳定默认）", "cpu"),
    ("CPU / GPU 对照", "compare"),
    ("GPU 实验", "gpu"),
)
PICKING_VALUES = frozenset(value for _, value in PICKING_MODES)
MAX_PICK_ID = 0xFFFFFF
POSTPROCESS_MODES = (
    ("原图", "none"),
    ("灰度", "grayscale"),
    ("反相", "invert"),
    ("边缘检测", "edge"),
)
ATTACHMENT_VIEWS = (
    ("颜色源", "color"),
    ("后处理输出", "postprocess"),
    ("对象 ID", "id"),
)
OFFSCREEN_SCALES = (("1×", 1), ("2×", 2))
POSTPROCESS_VALUES = frozenset(value for _, value in POSTPROCESS_MODES)
ATTACHMENT_VALUES = frozenset(value for _, value in ATTACHMENT_VIEWS)
MAX_OFFSCREEN_PIXELS = 16_000_000
MAX_OFFSCREEN_EDGE = 8192


def encode_pick_id(value):
    """Encode a non-negative 24-bit integer as an opaque RGB tuple."""
    value = int(value)
    if not 0 <= value <= MAX_PICK_ID:
        raise ValueError("pick ID must fit in 24 bits")
    return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF, 0xFF)


def decode_pick_id(red, green, blue):
    return ((int(red) & 0xFF) << 16) | ((int(green) & 0xFF) << 8) | (int(blue) & 0xFF)


@dataclass(frozen=True)
class PickComparison:
    cpu_shape_id: str = ""
    gpu_shape_id: str = ""
    cpu_ms: float = 0.0
    gpu_ms: float = 0.0
    matched: bool = True
    gpu_available: bool = False
    fallback_reason: str = ""


def validate_picking_mode(mode):
    mode = str(mode)
    if mode not in PICKING_VALUES:
        raise ValueError(f"Unsupported picking mode: {mode}")
    return mode


def validate_postprocess(mode):
    mode = str(mode)
    if mode not in POSTPROCESS_VALUES:
        raise ValueError(f"Unsupported postprocess mode: {mode}")
    return mode


def validate_attachment_view(view):
    view = str(view)
    if view not in ATTACHMENT_VALUES:
        raise ValueError(f"Unsupported attachment view: {view}")
    return view


def offscreen_dimensions(width, height, scale):
    scale = int(scale)
    if scale not in (1, 2):
        raise ValueError("offscreen scale must be 1 or 2")
    width, height = max(1, int(width)) * scale, max(1, int(height)) * scale
    pixels = width * height
    if width > MAX_OFFSCREEN_EDGE or height > MAX_OFFSCREEN_EDGE:
        raise ValueError(f"离屏尺寸 {width}×{height} 超过单边 {MAX_OFFSCREEN_EDGE} 限制")
    if pixels > MAX_OFFSCREEN_PIXELS:
        raise ValueError(
            f"离屏尺寸 {width}×{height} 共 {pixels:,} 像素，超过 {MAX_OFFSCREEN_PIXELS:,} 限制")
    return width, height


def estimated_target_bytes(width, height):
    """RGBA8+depth/stencil source plus RGBA8 postprocess destination."""
    return int(width) * int(height) * 12
