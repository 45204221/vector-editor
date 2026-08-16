"""工具管理器"""

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QMouseEvent

from .base_tool import (Tool, SelectTool, RectangleTool, EllipseTool, LineTool,
                          DiamondTool, RoundedRectTool, ParallelogramTool,
                          ResistorTool, CapacitorTool, InductorTool,
                          GroundTool, BatteryTool, DiodeTool, OrgNodeTool,
                          PolygonTool, PolylineTool, ConnectionTool, TextTool)


class ToolManager(QObject):
    """工具管理器"""

    # 信号定义
    tool_changed = pyqtSignal(Tool)      # 工具改变
    canvas_changed = pyqtSignal()        # 画布变化

    def __init__(self, graphics_view):
        super().__init__()
        self.graphics_view = graphics_view
        self.canvas = graphics_view.canvas
        self.current_tool = None
        self.tools = {}
        self._changing_tool = False

        # 初始化工具
        self._init_tools()

    def _init_tools(self) -> None:
        """初始化所有工具"""
        self.tools['select'] = SelectTool(self.graphics_view)
        self.tools['rectangle'] = RectangleTool(self.graphics_view)
        self.tools['ellipse'] = EllipseTool(self.graphics_view)
        self.tools['line'] = LineTool(self.graphics_view)
        self.tools['diamond'] = DiamondTool(self.graphics_view)
        self.tools['rounded_rect'] = RoundedRectTool(self.graphics_view)
        self.tools['parallelogram'] = ParallelogramTool(self.graphics_view)
        self.tools['resistor'] = ResistorTool(self.graphics_view)
        self.tools['capacitor'] = CapacitorTool(self.graphics_view)
        self.tools['inductor'] = InductorTool(self.graphics_view)
        self.tools['ground'] = GroundTool(self.graphics_view)
        self.tools['battery'] = BatteryTool(self.graphics_view)
        self.tools['diode'] = DiodeTool(self.graphics_view)
        self.tools['org_node'] = OrgNodeTool(self.graphics_view)
        self.tools['polygon'] = PolygonTool(self.graphics_view)
        self.tools['polyline'] = PolylineTool(self.graphics_view)
        self.tools['connection'] = ConnectionTool(self.graphics_view)
        self.tools['text'] = TextTool(self.graphics_view)

        # 默认选择工具
        self.set_tool('select')

    def set_tool(self, tool_name: str) -> None:
        """设置当前工具"""
        if self._changing_tool:
            return

        self._changing_tool = True
        try:
            if self.current_tool:
                self.current_tool.deactivate()

            if tool_name in self.tools:
                self.current_tool = self.tools[tool_name]
                self.current_tool.activate()
                self.tool_changed.emit(self.current_tool)
        finally:
            self._changing_tool = False

    def get_tool(self, tool_name: str) -> Tool:
        """获取指定工具"""
        return self.tools.get(tool_name)

    def get_current_tool(self) -> Tool:
        """获取当前工具"""
        return self.current_tool

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """鼠标按下事件"""
        if self.current_tool:
            try:
                self.current_tool.mousePressEvent(event)
            except Exception as e:
                print(f"Error in tool mousePressEvent: {e}")
                self.set_tool('select')

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """鼠标释放事件"""
        if self.current_tool:
            try:
                self.current_tool.mouseReleaseEvent(event)
            except Exception as e:
                print(f"Error in tool mouseReleaseEvent: {e}")
                self.set_tool('select')

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """鼠标移动事件"""
        if self.current_tool:
            try:
                self.current_tool.mouseMoveEvent(event)
            except Exception as e:
                print(f"Error in tool mouseMoveEvent: {e}")
                self.set_tool('select')

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """鼠标双击事件"""
        if self.current_tool:
            self.current_tool.mouseDoubleClickEvent(event)

    def get_tool_names(self) -> list:
        """获取所有工具名称"""
        return list(self.tools.keys())

    def get_tool_info(self, tool_name: str) -> dict:
        """获取工具信息"""
        if tool_name in self.tools:
            tool = self.tools[tool_name]
            return {
                'name': tool_name,
                'class': tool.__class__.__name__,
                'state': tool.state,
                'cursor': tool.cursor
            }
        return {}
