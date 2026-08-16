# 常见问题解决方案

## 1. PyQt5 安装问题

### 问题：ModuleNotFoundError: No module named 'PyQt5'

**解决方案：**

1. **使用虚拟环境**
```bash
# Windows
python -m venv venv
venv\Scripts\activate
pip install PyQt5

# Linux/Mac
python3 -m venv venv
source venv/bin/activate
pip install PyQt5
```

2. **如果使用 pip 失败，尝试 conda**
```bash
conda install pyqt
```

3. **如果仍然失败，尝试预编译版本**
```bash
pip install pyqt5 Wheels
```

## 2. 版本兼容性问题

### 问题：PyQt5 版本过高或过低

**解决方案：**
- 检查 Python 版本（需要 3.8+）
- 使用兼容的 PyQt5 版本
- 检查 Qt version：
```python
from PyQt5.QtCore import QT_VERSION_STR
print(f"Qt 版本: {QT_VERSION_STR}")
```

## 3. Windows 系统问题

### 问题：DLL 加载失败

**解决方案：**
1. 安装 Visual C++ Redistributable
2. 重新安装 PyQt5：
```bash
pip uninstall PyQt5 PyQt5-Qt5 PyQt5-sip
pip install PyQt5
```

## 4. Linux 系统问题

### 问题：缺少系统依赖

**解决方案：**
```bash
# Ubuntu/Debian
sudo apt-get install python3-pyqt5 python3-pyqt5-tools

# Fedora
sudo dnf install python3-qt5

# Arch
sudo pacman -S python-pyqt5
```

## 5. macOS 系统问题

### 问题：PyQt5 安装失败

**解决方案：**
1. 使用 Homebrew：
```bash
brew install python3
pip3 install PyQt5
```

2. 或使用 conda：
```bash
conda install pyqt
```

## 6. Python 版本问题

### 问题：版本不兼容

**解决方案：**
- 检查 Python 版本：
```bash
python --version
python3 --version
```
- 确保使用 Python 3.8 或更高版本

## 7. 运行时的显示问题

### 问题：程序启动后界面显示异常

**解决方案：**
1. 检查 DISPLAY 环境变量（Linux）：
```bash
export DISPLAY=:0
```

2. 或使用无头模式测试：
```python
app = QApplication([])
# ... 测试代码
```

## 8. 内存问题

### 问题：程序占用内存过高

**解决方案：**
1. 使用虚拟内存优化
2. 定期清理图形对象
3. 实现对象池模式

## 9. 字体渲染问题

### 问题：中文显示异常

**解决方案：**
1. 安装中文字体：
```bash
# Windows - 已包含
# Linux
sudo apt-get install fonts-wqy-microhei
```

2. 在代码中指定字体：
```python
font = QFont("WenQuanYi Micro Hei", 10)
```

## 10. 快速诊断命令

运行以下命令诊断环境：

```python
import sys
print(f"Python 版本: {sys.version}")

try:
    import PyQt5
    print(f"PyQt5 版本: {PyQt5.QtCore.PYQT_VERSION_STR}")
    print(f"Qt 版本: {PyQt5.QtCore.QT_VERSION_STR}")
except ImportError as e:
    print(f"PyQt5 未安装: {e}")

try:
    from PIL import Image
    print(f"PIL 版本: {Image.__version__}")
except ImportError as e:
    print(f"PIL 未安装: {e}")
```

## 获取帮助

如果问题仍然存在：

1. 查看 Python 和 PyQt5 的官方文档
2. 在 Stack Overflow 上搜索相关问题
3. 查看项目 Issues 页面