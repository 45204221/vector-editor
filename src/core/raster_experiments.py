"""Pure runtime configuration for the OpenGL shader/raster laboratory."""

from dataclasses import dataclass, replace


SHADER_MODES = (
    ("顶点色（基准）", "vertex_color"),
    ("屏幕冷暖渐变", "screen_gradient"),
    ("时间脉冲", "time_pulse"),
    ("Coverage 可视化", "coverage"),
)

BLEND_MODES = (
    ("标准 Alpha", "alpha"),
    ("加色混合", "additive"),
    ("关闭混合", "opaque"),
)

CLIP_MODES = (
    ("关闭", "none"),
    ("Scissor", "scissor"),
    ("Stencil", "stencil"),
)

_SHADER_VALUES = frozenset(value for _, value in SHADER_MODES)
_BLEND_VALUES = frozenset(value for _, value in BLEND_MODES)
_CLIP_VALUES = frozenset(value for _, value in CLIP_MODES)


@dataclass(frozen=True)
class RasterExperimentConfig:
    """Validated settings that never enter the editable document model."""

    shader_mode: str = "vertex_color"
    blend_mode: str = "alpha"
    clip_mode: str = "none"

    def __post_init__(self):
        if self.shader_mode not in _SHADER_VALUES:
            raise ValueError(f"Unsupported shader mode: {self.shader_mode}")
        if self.blend_mode not in _BLEND_VALUES:
            raise ValueError(f"Unsupported blend mode: {self.blend_mode}")
        if self.clip_mode not in _CLIP_VALUES:
            raise ValueError(f"Unsupported clip mode: {self.clip_mode}")

    def changed(self, shader_mode=None, blend_mode=None, clip_mode=None):
        return replace(
            self,
            shader_mode=self.shader_mode if shader_mode is None else shader_mode,
            blend_mode=self.blend_mode if blend_mode is None else blend_mode,
            clip_mode=self.clip_mode if clip_mode is None else clip_mode,
        )

    def as_dict(self):
        return {
            "shader_mode": self.shader_mode,
            "blend_mode": self.blend_mode,
            "clip_mode": self.clip_mode,
        }

