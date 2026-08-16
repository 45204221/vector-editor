"""Runtime configuration and CPU stage tracing for the M17 3D pipeline."""

from dataclasses import dataclass, replace
import math

from PyQt5.QtGui import QMatrix4x4, QVector3D, QVector4D


VIEW_MODES = (("最终光照", "final"), ("线框", "wireframe"),
              ("法线 RGB", "normals"), ("相机深度", "depth"),
              ("光源深度 / Shadow Map", "shadow_map"))
ATTACHMENT_MODES = (("Normal RGB", "normal"),
                    ("Camera Depth", "depth"),
                    ("Shadow Map", "shadow"),
                    ("G-Position", "g_position"),
                    ("G-Normal", "g_normal"),
                    ("G-Albedo", "g_albedo"))


@dataclass(frozen=True)
class Pipeline3DConfig:
    source_mode: str = "cube"
    extrusion_depth: float = 0.7
    view_mode: str = "final"
    depth_test: bool = True
    cull_back_faces: bool = True
    fov: float = 45.0
    near: float = 0.1
    far: float = 100.0
    camera_yaw: float = 30.0
    camera_pitch: float = 20.0
    camera_distance: float = 5.0
    rotation_x: float = -12.0
    rotation_y: float = 28.0
    rotation_z: float = 0.0
    trace_vertex: int = 0
    light_x: float = 2.8
    light_y: float = 4.2
    light_z: float = 3.0
    ambient: float = 0.16
    diffuse: float = 0.82
    specular: float = 0.55
    shininess: float = 48.0
    shadows: bool = True
    shadow_resolution: int = 512
    shadow_bias: float = 0.003
    pcf_radius: int = 1
    render_path: str = "forward"
    light_count: int = 4

    def __post_init__(self):
        if self.source_mode not in ("cube", "selection"):
            raise ValueError("invalid 3D mesh source")
        if self.view_mode not in {value for _, value in VIEW_MODES}:
            raise ValueError("invalid 3D view mode")
        if self.extrusion_depth <= 0:
            raise ValueError("extrusion depth must be positive")
        if not 10.0 <= self.fov <= 120.0:
            raise ValueError("FOV must be between 10 and 120 degrees")
        if self.near <= 0 or self.far <= self.near:
            raise ValueError("near/far plane values are invalid")
        if self.camera_distance <= 1.1:
            raise ValueError("camera distance is too small")
        if any(value < 0.0 for value in
               (self.ambient, self.diffuse, self.specular)):
            raise ValueError("lighting strengths must be non-negative")
        if not 1.0 <= self.shininess <= 256.0:
            raise ValueError("shininess must be between 1 and 256")
        if self.shadow_resolution not in (256, 512, 1024):
            raise ValueError("shadow resolution must be 256, 512 or 1024")
        if not 0.0 <= self.shadow_bias <= 0.05:
            raise ValueError("shadow bias must be between 0 and 0.05")
        if self.pcf_radius not in (0, 1, 2):
            raise ValueError("PCF radius must be 0, 1 or 2")
        if self.render_path not in ("forward", "deferred"):
            raise ValueError("render path must be forward or deferred")
        if self.light_count not in (1, 4, 8):
            raise ValueError("light count must be 1, 4 or 8")

    def changed(self, **changes):
        return replace(self, **changes)


def pipeline_matrices(config, aspect):
    model = QMatrix4x4()
    model.rotate(config.rotation_x, 1.0, 0.0, 0.0)
    model.rotate(config.rotation_y, 0.0, 1.0, 0.0)
    model.rotate(config.rotation_z, 0.0, 0.0, 1.0)
    yaw, pitch = math.radians(config.camera_yaw), math.radians(config.camera_pitch)
    distance = config.camera_distance
    eye = QVector3D(distance * math.cos(pitch) * math.sin(yaw),
                    distance * math.sin(pitch),
                    distance * math.cos(pitch) * math.cos(yaw))
    view = QMatrix4x4()
    view.lookAt(eye, QVector3D(0.0, 0.0, 0.0), QVector3D(0.0, 1.0, 0.0))
    projection = QMatrix4x4()
    projection.perspective(config.fov, max(1e-6, float(aspect)),
                           config.near, config.far)
    return model, view, projection


def camera_position(config):
    yaw, pitch = math.radians(config.camera_yaw), math.radians(config.camera_pitch)
    distance = config.camera_distance
    return QVector3D(distance * math.cos(pitch) * math.sin(yaw),
                     distance * math.sin(pitch),
                     distance * math.cos(pitch) * math.cos(yaw))


def light_matrices(config):
    """Return the world-to-light clip matrix used by both passes."""
    light = QVector3D(config.light_x, config.light_y, config.light_z)
    view = QMatrix4x4()
    view.lookAt(light, QVector3D(0.0, -0.35, 0.0), QVector3D(0.0, 1.0, 0.0))
    projection = QMatrix4x4()
    projection.perspective(58.0, 1.0, 0.5, 20.0)
    return view, projection, projection * view


def blinn_phong_components(normal, world_position, config):
    """CPU reference for the three Shader lighting terms."""
    n = QVector3D(*map(float, normal)); n.normalize()
    p = QVector3D(*map(float, world_position))
    light_direction = QVector3D(config.light_x, config.light_y,
                                config.light_z) - p
    light_direction.normalize()
    view_direction = camera_position(config) - p; view_direction.normalize()
    halfway = light_direction + view_direction
    if halfway.lengthSquared() > 1e-12:
        halfway.normalize()
    lambert = max(0.0, QVector3D.dotProduct(n, light_direction))
    specular_angle = max(0.0, QVector3D.dotProduct(n, halfway))
    return {
        "ambient": float(config.ambient),
        "diffuse": float(config.diffuse * lambert),
        "specular": float(config.specular * (specular_angle ** config.shininess)
                          if lambert > 0.0 else 0.0),
    }


def scene_lights(config):
    """Deterministic light set shared by Forward and Deferred paths."""
    positions = ((config.light_x, config.light_y, config.light_z),
                 (-3.2, 1.8, 2.2), (3.0, 1.2, -2.8), (-1.0, 3.6, -3.0),
                 (0.2, 1.0, 3.8), (3.8, 2.8, 0.2), (-3.8, 3.0, -0.4),
                 (0.0, 4.8, 0.0))
    colors = ((1.0, 0.96, 0.88), (1.0, 0.22, 0.15), (0.15, 0.62, 1.0),
              (0.7, 0.25, 1.0), (0.18, 1.0, 0.52), (1.0, 0.66, 0.12),
              (0.12, 0.95, 1.0), (1.0, 0.2, 0.65))
    return tuple((positions[index], colors[index])
                 for index in range(config.light_count))


def _tuple(vector):
    return (float(vector.x()), float(vector.y()),
            float(vector.z()), float(vector.w()))


def trace_pipeline_vertex(vertex, config, width, height):
    position = QVector4D(float(vertex[0]), float(vertex[1]), float(vertex[2]), 1.0)
    model, view, projection = pipeline_matrices(config, width / max(1.0, height))
    world = model * position
    view_position = view * world
    clip = projection * view_position
    w = clip.w()
    ndc = QVector4D(clip.x() / w, clip.y() / w, clip.z() / w, 1.0) if abs(w) > 1e-9 else QVector4D()
    screen = QVector4D((ndc.x() * 0.5 + 0.5) * width,
                       (1.0 - (ndc.y() * 0.5 + 0.5)) * height,
                       ndc.z() * 0.5 + 0.5, 1.0)
    inside = (w > 0 and abs(clip.x()) <= w and abs(clip.y()) <= w
              and abs(clip.z()) <= w)
    return {
        "object": _tuple(position), "world": _tuple(world),
        "view": _tuple(view_position), "clip": _tuple(clip),
        "ndc": _tuple(ndc), "screen": _tuple(screen),
        "inside_clip": bool(inside),
        "model": model, "view_matrix": view, "projection": projection,
    }
