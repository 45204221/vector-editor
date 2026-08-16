"""数据序列化模块"""

import json
import copy
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

from .shape import Shape, ShapeType
from .selection import SelectionManager
from PyQt5.QtCore import Qt

class Serializer:
    """图形数据序列化器"""

    def __init__(self):
        self.version = "1.0"

    def save_to_file(self, shapes: List[Shape], file_path: str, metadata=None) -> bool:
        """保存图形数据到文件"""
        try:
            # 创建目录（如果不存在）
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            # 准备数据
            data = {
                "version": self.version,
                "created_at": datetime.now().isoformat(),
                "shapes": [shape.to_dict() for shape in shapes],
            }
            if metadata:
                data.update(metadata)

            # 写入文件
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            return True

        except Exception as e:
            print(f"保存文件失败: {e}")
            return False

    def load_from_file(self, file_path: str) -> Optional[List[Shape]]:
        """从文件加载图形数据"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.loaded_layers = data.get("layers", [])
            self.loaded_springs = data.get("springs", [])

            # 检查版本兼容性
            version = data.get("version", "1.0")
            if version != self.version:
                print(f"版本不兼容: 文件版本 {version}, 当前版本 {self.version}")

            # 解析图形数据
            shapes = []
            for shape_data in data.get("shapes", []):
                shape = Shape.from_dict(shape_data)
                shapes.append(shape)

            return shapes

        except Exception as e:
            print(f"加载文件失败: {e}")
            return None

    def export_to_svg(self, shapes: List[Shape], file_path: str) -> bool:
        """导出为 SVG 格式"""
        try:
            # 创建目录
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            # SVG 头部
            svg_content = [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<svg xmlns="http://www.w3.org/2000/svg"',
                f'     width="{self._get_svg_width(shapes)}"',
                f'     height="{self._get_svg_height(shapes)}"',
                '     viewBox="0 0 {} {}">'.format(
                    self._get_svg_width(shapes), self._get_svg_height(shapes)
                ),
                "<g>",
            ]

            # 添加图形
            for shape in shapes:
                if shape.visible:
                    svg_element = self._shape_to_svg(shape)
                    if svg_element:
                        svg_content.append(svg_element)

            # SVG 底部
            svg_content.extend(["</g>", "</svg>"])

            # 写入文件
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(svg_content))

            return True

        except Exception as e:
            print(f"导出 SVG 失败: {e}")
            return False

    def _get_svg_width(self, shapes: List[Shape]) -> int:
        """获取 SVG 宽度"""
        if not shapes:
            return 800

        max_x = 0
        for shape in shapes:
            rect = shape.bounding_rect()
            max_x = max(max_x, rect.right())

        return int(max_x + 50)  # 留一些边距

    def _get_svg_height(self, shapes: List[Shape]) -> int:
        """获取 SVG 高度"""
        if not shapes:
            return 600

        max_y = 0
        for shape in shapes:
            rect = shape.bounding_rect()
            max_y = max(max_y, rect.bottom())

        return int(max_y + 50)  # 留一些边距

    def _shape_to_svg(self, shape: Shape) -> Optional[str]:
        """将图形转换为 SVG 元素"""
        # 这里简化处理，实际实现需要根据不同图形类型生成对应的 SVG
        style = shape.style

        # 设置样式
        stroke = style.pen_color
        stroke_width = style.pen_width
        fill = style.brush_color if style.brush_style != Qt.NoBrush else "none"
        opacity = style.opacity

        if hasattr(shape, "rect"):
            # 矩形或椭圆
            rect = shape.bounding_rect()
            if shape.shape_type == ShapeType.RECTANGLE:
                return f'<rect x="{rect.x()}" y="{rect.y()}" width="{rect.width()}" height="{rect.height()}" \
                    stroke="{stroke}" stroke-width="{stroke_width}" fill="{fill}" opacity="{opacity}" />'
            elif shape.shape_type == ShapeType.ELLIPSE:
                return f'<ellipse cx="{rect.x() + rect.width()/2}" cy="{rect.y() + rect.height()/2}" \
                    rx="{rect.width()/2}" ry="{rect.height()/2}" \
                    stroke="{stroke}" stroke-width="{stroke_width}" fill="{fill}" opacity="{opacity}" />'

        elif hasattr(shape, "line"):
            # 直线
            p1, p2 = shape.line
            return f'<line x1="{p1.x()}" y1="{p1.y()}" x2="{p2.x()}" y2="{p2.y()}" \
                stroke="{stroke}" stroke-width="{stroke_width}" opacity="{opacity}" />'

        # 其他图形类型的 SVG 转换可以在这里添加
        return None

    def save_selection_state(
        self, selection_manager: SelectionManager, file_path: str
    ) -> bool:
        """保存选择状态"""
        try:
            data = {
                "version": self.version,
                "selected_shapes": [
                    shape.to_dict() for shape in selection_manager.get_selected_shapes()
                ],
            }

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            return True

        except Exception as e:
            print(f"保存选择状态失败: {e}")
            return False

    def load_selection_state(
        self, selection_manager: SelectionManager, file_path: str
    ) -> bool:
        """加载选择状态"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            selection_manager.clear_selection()
            for shape_data in data.get("selected_shapes", []):
                shape = Shape.from_dict(shape_data)
                selection_manager.add_shape(shape)

            return True

        except Exception as e:
            print(f"加载选择状态失败: {e}")
            return False


class HistoryManager:
    """纯数据文档快照历史；不持有图元或渲染器对象。"""

    def __init__(self, max_history: int = 50):
        self.max_history = max_history
        self.history = []
        self.current_index = -1

    def add_state(self, state: Dict[str, Any]) -> bool:
        """添加状态，若与当前状态相同则不创建记录。"""
        state = copy.deepcopy(state)
        if self.current_index >= 0 and self.history[self.current_index] == state:
            return False
        # 如果当前不在最新状态，删除后面的历史
        if self.current_index < len(self.history) - 1:
            self.history = self.history[: self.current_index + 1]

        self.history.append(state)
        self.current_index += 1

        # 限制历史记录长度
        if len(self.history) > self.max_history:
            self.history.pop(0)
            self.current_index -= 1
        return True

    def undo(self) -> Optional[Dict[str, Any]]:
        """撤销"""
        if self.current_index > 0:
            self.current_index -= 1
            return copy.deepcopy(self.history[self.current_index])
        return None

    def redo(self) -> Optional[Dict[str, Any]]:
        """重做"""
        if self.current_index < len(self.history) - 1:
            self.current_index += 1
            return copy.deepcopy(self.history[self.current_index])
        return None

    def can_undo(self) -> bool:
        """是否可以撤销"""
        return self.current_index > 0

    def can_redo(self) -> bool:
        """是否可以重做"""
        return self.current_index < len(self.history) - 1

    def clear(self) -> None:
        """清除历史记录"""
        self.history = []
        self.current_index = -1
