#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
矢量图形编辑器启动脚本
"""

import sys
import os
import traceback

# 添加src目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(current_dir, 'src')
sys.path.insert(0, src_dir)

def main():
    """主函数"""
    print("=" * 50)
    print("矢量图形编辑器")
    print("=" * 50)
    print()

    try:
        # 导入主程序
        from main import main as app_main

        # 运行应用程序
        app_main()

    except ImportError as e:
        print(f"导入错误: {e}")
        print("请确保所有文件都在正确的位置。")
        print()
        print("文件结构应该是:")
        print("vector_editor/")
        print("├── src/")
        print("│   ├── main.py")
        print("│   ├── core/")
        print("│   ├── ui/")
        print("│   ├── tools/")
        print("│   └── widgets/")
        print()

    except Exception as e:
        print(f"程序运行出错: {e}")
        print()
        print("错误详情:")
        traceback.print_exc()

    finally:
        print()
        print("程序已退出。")

if __name__ == "__main__":
    main()