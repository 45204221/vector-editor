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
class CanvasHdrConfig:
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
