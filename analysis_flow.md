# 绘图工具事件流分析

## 事件流程概述

1. **用户点击工具栏按钮** → Toolbar.on_rectangle_tool() → GraphicsView.set_tool()
2. **用户在画布上按下鼠标** → GraphicsView.mousePressEvent() → ToolManager.mousePressEvent()
3. **用户拖动鼠标** → GraphicsView.mouseMoveEvent() → ToolManager.mouseMoveEvent()
4. **用户释放鼠标** → GraphicsView.mouseReleaseEvent() → ToolManager.mouseReleaseEvent()

## 关键组件检查

### 1. Toolbar（工具栏）
- ✓ 按钮连接正确
- ✓ 工具切换方法存在

### 2. GraphicsView（图形视图）
- ✓ 事件转换方法存在
- ✓ 事件转发存在

### 3. ToolManager（工具管理器）
- ✓ 工具初始化
- ✓ 事件转发存在

### 4. 绘图工具（RectangleTool, EllipseTool, LineTool）
- ✓ 所有必要方法存在
- ✓ update_temp_shape 方法已实现

## 可能的问题点

### 1. 事件类型问题
在 GraphicsView.mapToSceneEvent() 中，我们手动设置了事件类型。这可能有问题。

### 2. 事件坐标问题
scenePos() 可能没有正确设置。

### 3. 工具状态问题
工具的状态可能没有正确管理。

## 诊断建议

1. 检查 GraphicsView.mapToSceneEvent() 的实现
2. 检查 DrawTool.mousePressEvent() 的调用
3. 检查 DrawTool.update_temp_shape() 的实现
4. 检查场景更新机制

## 修复策略

1. 简化事件转换逻辑
2. 确保事件正确传递
3. 添加更多调试信息
4. 检查场景更新机制