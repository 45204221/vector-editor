@echo off
echo 正在安装矢量图形编辑器依赖...
echo.

:: 创建虚拟环境（如果不存在）
if not exist "venv" (
    echo 创建虚拟环境...
    python -m venv venv
    echo.
)

:: 激活虚拟环境
call venv\Scripts\activate.bat
echo 已激活虚拟环境
echo.

:: 升级pip
echo 升级pip...
python -m pip install --upgrade pip
echo.

:: 安装依赖
echo 安装项目依赖...
pip install -r requirements.txt
echo.

:: 安装开发依赖（可选）
echo 是否要安装开发依赖？(y/n)
set /p dev_install=
if /i "%dev_install%"=="y" (
    echo 安装开发依赖...
    pip install -e ".[dev]"
    echo.
)

echo.
echo 安装完成！
echo 运行程序：python src/main.py
echo.
pause