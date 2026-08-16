#!/bin/bash

echo "正在安装矢量图形编辑器依赖..."
echo

# 检查 Python 版本
python_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
required_version="3.8"

if python3 -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)"; then
    echo "Python 版本检查通过: $python_version"
else
    echo "错误: 需要 Python 3.8 或更高版本，当前版本: $python_version"
    exit 1
fi

# 创建虚拟环境（如果不存在）
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
    echo
fi

# 激活虚拟环境
echo "激活虚拟环境..."
source venv/bin/activate
echo

# 升级pip
echo "升级pip..."
python -m pip install --upgrade pip
echo

# 安装依赖
echo "安装项目依赖..."
pip install -r requirements.txt
echo

# 安装开发依赖（可选）
read -p "是否要安装开发依赖？(y/n): " dev_install
if [[ $dev_install =~ ^[Yy]$ ]]; then
    echo "安装开发依赖..."
    pip install -e ".[dev]"
    echo
fi

echo
echo "安装完成！"
echo "运行程序: python src/main.py"
echo "退出虚拟环境: deactivate"