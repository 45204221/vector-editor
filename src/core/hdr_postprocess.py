"""Pure HDR tone-mapping contracts shared by the canvas and tests."""

from dataclasses import dataclass, replace
import math


TONE_MAPPERS = (
    ("Linear Clamp", "linear"),
    ("Reinhard", "reinhard"),
    ("ACES Filmic", "aces"),
)

HDR_DEBUG_VIEWS = (
    ("最终画面", "final"),
    ("HDR 亮度热力图", "heatmap"),
    ("过曝区域", "overexposure"),
)

_TONE_MAPPER_VALUES = frozenset(value for _, value in TONE_MAPPERS)
_DEBUG_VALUES = frozenset(value for _, value in HDR_DEBUG_VIEWS)


@dataclass(frozen=True)
class ToneMappingConfig:
    """Backend-neutral runtime configuration for an HDR display transform."""

    enabled: bool = False
    tone_mapper: str = "reinhard"
    exposure: float = 1.0
    debug_view: str = "final"

    def __post_init__(self):
        if self.tone_mapper not in _TONE_MAPPER_VALUES:
            raise ValueError(f"Unsupported tone mapper: {self.tone_mapper}")
        if self.debug_view not in _DEBUG_VALUES:
            raise ValueError(f"Unsupported HDR debug view: {self.debug_view}")
        if not math.isfinite(self.exposure) or not 0.05 <= self.exposure <= 8.0:
            raise ValueError("exposure must be finite and between 0.05 and 8.0")

    def changed(self, enabled=None, tone_mapper=None, exposure=None,
                debug_view=None):
        return replace(
            self,
            enabled=self.enabled if enabled is None else bool(enabled),
            tone_mapper=self.tone_mapper if tone_mapper is None else str(tone_mapper),
            exposure=self.exposure if exposure is None else float(exposure),
            debug_view=self.debug_view if debug_view is None else str(debug_view),
        )

    def as_dict(self):
        return {
            "enabled": self.enabled,
            "tone_mapper": self.tone_mapper,
            "exposure": self.exposure,
            "debug_view": self.debug_view,
        }


# M20 exposed this name to the canvas/UI.  Keep it as an alias so the shared
# M21 contract does not break the existing public surface or saved test code.
CanvasHdrConfig = ToneMappingConfig


def srgb_to_linear(value):
    """Decode one IEC 61966-2-1 sRGB channel into linear light."""
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("sRGB channel must be finite and between 0 and 1")
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def linear_to_srgb(value):
    """Encode one non-negative linear-light channel as IEC sRGB."""
    value = float(value)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError("linear channel must be finite and non-negative")
    if value <= 0.0031308:
        return 12.92 * value
    return 1.055 * (value ** (1.0 / 2.4)) - 0.055


def relative_luminance(rgb):
    """Return Rec.709 relative luminance for a linear RGB triplet."""
    values = tuple(float(value) for value in rgb)
    if len(values) != 3 or not all(math.isfinite(value) for value in values):
        raise ValueError("rgb must contain three finite values")
    if any(value < 0.0 for value in values):
        raise ValueError("linear RGB channels cannot be negative")
    return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2]


def bloom_soft_threshold(rgb, threshold=1.0, knee=0.5):
    """Return the linear HDR contribution selected for Bloom."""
    values = tuple(float(value) for value in rgb)
    threshold, knee = float(threshold), float(knee)
    if len(values) != 3 or not all(math.isfinite(value) for value in values):
        raise ValueError("rgb must contain three finite values")
    if any(value < 0.0 for value in values):
        raise ValueError("HDR color channels cannot be negative")
    if not math.isfinite(threshold) or threshold < 0.0:
        raise ValueError("threshold must be finite and non-negative")
    if not math.isfinite(knee) or not 0.0 <= knee <= 1.0:
        raise ValueError("knee must be finite and between 0 and 1")
    brightness = max(values)
    soft_width = max(1e-6, threshold * knee)
    soft = max(0.0, min(2.0 * soft_width,
                       brightness - threshold + soft_width))
    soft = soft * soft / (4.0 * soft_width + 1e-6)
    contribution = max(soft, brightness - threshold) / max(brightness, 1e-6)
    return tuple(value * contribution for value in values)


def log_luminance_histogram(luminances, bins=64, min_ev=-12.0, max_ev=4.0):
    """Bin positive linear luminance samples in a bounded log2 domain."""
    bins = int(bins); min_ev = float(min_ev); max_ev = float(max_ev)
    if bins < 2 or bins > 256 or not min_ev < max_ev:
        raise ValueError("invalid histogram domain")
    histogram = [0] * bins
    for sample in luminances:
        value = float(sample)
        if not math.isfinite(value) or value < 0.0:
            raise ValueError("luminance samples must be finite and non-negative")
        ev = math.log(max(value, 2.0 ** min_ev), 2.0)
        normalized = max(0.0, min(1.0, (ev - min_ev) / (max_ev - min_ev)))
        index = min(bins - 1, int(normalized * bins))
        histogram[index] += 1
    return tuple(histogram)


def exposure_from_histogram(histogram, min_ev=-12.0, max_ev=4.0,
                            low_percentile=0.02, high_percentile=0.98,
                            middle_grey=0.18, compensation_ev=0.0):
    """Estimate exposure from a percentile-clipped log-luminance histogram."""
    values = tuple(int(value) for value in histogram)
    if len(values) < 2 or any(value < 0 for value in values):
        raise ValueError("histogram must contain at least two non-negative bins")
    min_ev, max_ev = float(min_ev), float(max_ev)
    low_percentile, high_percentile = float(low_percentile), float(high_percentile)
    middle_grey, compensation_ev = float(middle_grey), float(compensation_ev)
    if not min_ev < max_ev or not 0.0 <= low_percentile < high_percentile <= 1.0:
        raise ValueError("invalid exposure histogram range")
    if not math.isfinite(middle_grey) or middle_grey <= 0.0:
        raise ValueError("middle grey must be finite and positive")
    total = sum(values)
    if total <= 0:
        return 1.0
    low_count, high_count = total * low_percentile, total * high_percentile
    cumulative = 0
    weighted_ev = 0.0
    selected = 0
    width = (max_ev - min_ev) / len(values)
    for index, count in enumerate(values):
        start, end = cumulative, cumulative + count
        included = max(0.0, min(end, high_count) - max(start, low_count))
        if included > 0.0:
            weighted_ev += (min_ev + (index + 0.5) * width) * included
            selected += included
        cumulative = end
    average_ev = weighted_ev / selected if selected > 0.0 else 0.0
    average_luminance = 2.0 ** average_ev
    target = middle_grey * (2.0 ** compensation_ev) / max(average_luminance, 1e-6)
    return max(0.05, min(8.0, target))


def adapt_exposure(current, target, delta_seconds,
                   brighten_speed=3.0, darken_speed=1.5):
    """Exponentially approach target exposure with asymmetric eye adaptation."""
    current, target, delta_seconds = map(float, (current, target, delta_seconds))
    brighten_speed, darken_speed = map(float, (brighten_speed, darken_speed))
    if (not all(math.isfinite(value) for value in
                (current, target, delta_seconds, brighten_speed, darken_speed))
            or current <= 0.0 or target <= 0.0 or delta_seconds < 0.0
            or brighten_speed <= 0.0 or darken_speed <= 0.0):
        raise ValueError("invalid exposure adaptation input")
    speed = brighten_speed if target > current else darken_speed
    blend = 1.0 - math.exp(-speed * delta_seconds)
    return current + (target - current) * blend


def tone_map_rgb(rgb, exposure=1.0, tone_mapper="reinhard", gamma=2.2):
    """Map a non-negative linear HDR RGB triplet into display RGB."""
    values = tuple(float(value) for value in rgb)
    exposure, gamma = float(exposure), float(gamma)
    if len(values) != 3 or not all(math.isfinite(value) for value in values):
        raise ValueError("rgb must contain three finite values")
    if any(value < 0.0 for value in values):
        raise ValueError("HDR color channels cannot be negative")
    if tone_mapper not in _TONE_MAPPER_VALUES:
        raise ValueError(f"Unsupported tone mapper: {tone_mapper}")
    if not math.isfinite(exposure) or exposure < 0.0:
        raise ValueError("exposure must be finite and non-negative")
    if not math.isfinite(gamma) or gamma <= 0.0:
        raise ValueError("gamma must be finite and positive")
    exposed = tuple(value * exposure for value in values)
    if tone_mapper == "linear":
        mapped = tuple(min(1.0, value) for value in exposed)
    elif tone_mapper == "reinhard":
        mapped = tuple(value / (1.0 + value) for value in exposed)
    else:
        # Narkowicz ACES filmic approximation, intentionally shared with GLSL/C++.
        mapped = tuple(max(0.0, min(1.0,
            (value * (2.51 * value + 0.03)) /
            (value * (2.43 * value + 0.59) + 0.14))) for value in exposed)
    inverse_gamma = 1.0 / gamma
    return tuple(value ** inverse_gamma for value in mapped)
