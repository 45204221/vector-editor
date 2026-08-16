"""Qt-rasterized bitmap glyph atlas and API-neutral GPU text vertices."""

from dataclasses import dataclass, replace
import struct

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import (QColor, QFont, QFontMetricsF, QImage, QPainter,
                         QPainterPath)


ATLAS_SIZE = (1024, 1024)
CELL_SIZE = 64
RASTER_PIXEL_SIZE = 48
MAX_GLYPHS = (ATLAS_SIZE[0] // CELL_SIZE) * (ATLAS_SIZE[1] // CELL_SIZE)
TEXT_VERTEX_FLOATS = 8
TEXT_VERTEX_STRIDE = TEXT_VERTEX_FLOATS * 4


@dataclass(frozen=True)
class GpuTextConfig:
    enabled: bool = False
    show_demo: bool = True

    def changed(self, **changes):
        return replace(self, **changes)


@dataclass(frozen=True)
class GlyphCell:
    character: str
    uv_rect: tuple
    advance: float


@dataclass(frozen=True)
class GlyphTextFrame:
    key: tuple
    image: QImage
    cells: dict
    vertices: tuple
    payload: bytes
    ranges: tuple
    fallback_indexes: tuple
    glyph_count: int

    @property
    def vertex_count(self):
        return len(self.vertices) // TEXT_VERTEX_FLOATS


def text_commands_key(commands):
    return tuple((command.shape_id, command.local_rect, command.transform,
                  command.color, command.text, command.font_size)
                 for command in commands)


def _font(point_size=None, pixel_size=None):
    font = QFont()
    if pixel_size is not None:
        font.setPixelSize(int(pixel_size))
    elif point_size is not None:
        font.setPointSizeF(max(1.0, float(point_size)))
    return font


def build_glyph_atlas(characters):
    """Return a deterministic RGBA atlas and cells for up to MAX_GLYPHS."""
    unique = sorted({character for character in characters
                     if character and not character.isspace()})[:MAX_GLYPHS]
    image = QImage(ATLAS_SIZE[0], ATLAS_SIZE[1], QImage.Format_RGBA8888)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.TextAntialiasing)
    painter.setPen(QColor(255, 255, 255, 255))
    font = _font(pixel_size=RASTER_PIXEL_SIZE)
    painter.setFont(font)
    metrics = QFontMetricsF(font)
    cells = {}
    columns = ATLAS_SIZE[0] // CELL_SIZE
    for index, character in enumerate(unique):
        column, row = index % columns, index // columns
        left, top = column * CELL_SIZE, row * CELL_SIZE
        advance = metrics.horizontalAdvance(character)
        x = left + (CELL_SIZE - advance) / 2.0
        y = top + (CELL_SIZE - metrics.height()) / 2.0 + metrics.ascent()
        # QPainterPath is deterministic on Qt's offscreen platform as well as
        # the Windows GUI platform, while direct drawText may depend on the
        # platform text paint engine selected by the test environment.
        path = QPainterPath()
        path.addText(QPointF(x, y), font, character)
        painter.fillPath(path, QColor(255, 255, 255, 255))
        cells[character] = GlyphCell(
            character,
            (left / ATLAS_SIZE[0], top / ATLAS_SIZE[1],
             (left + CELL_SIZE) / ATLAS_SIZE[0],
             (top + CELL_SIZE) / ATLAS_SIZE[1]),
            advance,
        )
    painter.end()
    return image, cells


def _map_point(point, transform):
    x, y = point
    m11, m12, m21, m22, dx, dy = transform
    return (m11 * x + m21 * y + dx,
            m12 * x + m22 * y + dy)


def _append_quad(values, bounds, uv, color, transform):
    left, top, right, bottom = bounds
    u0, v0, u1, v1 = uv
    corners = (
        ((left, top), (u0, v0)), ((right, top), (u1, v0)),
        ((right, bottom), (u1, v1)), ((left, top), (u0, v0)),
        ((right, bottom), (u1, v1)), ((left, bottom), (u0, v1)),
    )
    for point, texture in corners:
        scene = _map_point(point, transform)
        values.extend((*scene, *texture, *color))


def build_text_frame(commands):
    """Build one atlas and scene-space triangle stream for text commands."""
    key = text_commands_key(commands)
    characters = [character for command in commands for character in command.text
                  if not character.isspace()]
    image, cells = build_glyph_atlas(characters)
    available = set(cells)
    canonical_font = _font(pixel_size=RASTER_PIXEL_SIZE)
    canonical_metrics = QFontMetricsF(canonical_font)
    canonical_height = max(1.0, canonical_metrics.height())
    vertices = []
    ranges = []
    fallbacks = []
    rendered_glyphs = 0

    for command_index, command in enumerate(commands):
        first_vertex = len(vertices) // TEXT_VERTEX_FLOATS
        required = {character for character in command.text
                    if not character.isspace()}
        if not required.issubset(available) or len(command.local_rect) < 3:
            fallbacks.append(command_index)
            ranges.append((first_vertex, 0))
            continue
        first, third = command.local_rect[0], command.local_rect[2]
        left, right = sorted((float(first[0]), float(third[0])))
        top, bottom = sorted((float(first[1]), float(third[1])))
        font = _font(point_size=command.font_size)
        metrics = QFontMetricsF(font)
        line_height = max(1.0, metrics.height())
        scale = line_height / canonical_height
        cursor_x, line_top = left, top
        for character in command.text:
            if character == "\r":
                continue
            if character == "\n":
                cursor_x, line_top = left, line_top + line_height
                continue
            advance = metrics.horizontalAdvance(character)
            if cursor_x > left and cursor_x + advance > right:
                cursor_x, line_top = left, line_top + line_height
            # Match QPainter's useful behavior for a font taller than the
            # original text box: keep the first (partially visible) line, but
            # stop additional wrapped lines once the box is exhausted.
            if line_top > top and line_top + line_height > bottom:
                break
            if not character.isspace():
                cell = cells[character]
                horizontal_padding = (CELL_SIZE - cell.advance) / 2.0 * scale
                vertical_padding = (CELL_SIZE - canonical_height) / 2.0 * scale
                glyph_left = cursor_x - horizontal_padding
                glyph_top = line_top - vertical_padding
                size = CELL_SIZE * scale
                _append_quad(vertices,
                             (glyph_left, glyph_top,
                              glyph_left + size, glyph_top + size),
                             cell.uv_rect, command.color, command.transform)
                rendered_glyphs += 1
            cursor_x += advance
        ranges.append((first_vertex,
                       len(vertices) // TEXT_VERTEX_FLOATS - first_vertex))

    payload = (struct.pack("<{}f".format(len(vertices)), *vertices)
               if vertices else b"")
    return GlyphTextFrame(key, image, cells, tuple(vertices), payload,
                          tuple(ranges), tuple(fallbacks), rendered_glyphs)
