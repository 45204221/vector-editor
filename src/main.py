"""矢量图形编辑器主程序入口"""

import sys
import os

# 添加 src 目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
src_dir = os.path.join(current_dir)
sys.path.insert(0, src_dir)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QSurfaceFormat

from ui.main_window import MainWindow


def main():
    """主函数"""
    # 必须在 QApplication/任何 OpenGL context 创建前请求 MSAA 和 stencil；
    # 驱动不支持时以后端实际 format 为准，并保留 coverage/scissor 回退。
    surface_format = QSurfaceFormat.defaultFormat()
    surface_format.setSamples(max(4, surface_format.samples()))
    surface_format.setStencilBufferSize(max(8, surface_format.stencilBufferSize()))
    QSurfaceFormat.setDefaultFormat(surface_format)
    app = QApplication(sys.argv)

    # 设置应用程序信息
    app.setApplicationName("矢量图形编辑器")
    app.setApplicationVersion("1.0.0")

    # 设置样式
    app.setStyle("Fusion")

    # 创建主窗口
    window = MainWindow()
    window.show()

    # 运行应用程序
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
