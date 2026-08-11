@echo off
chcp 65001 >nul
echo ========================================
echo 零售通知自动分发工具 - 打包脚本
echo ========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到Python，请先安装Python
    pause & exit /b 1
)

echo 正在安装依赖...
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
if errorlevel 1 (
    echo 错误: 安装依赖失败
    pause & exit /b 1
)

echo.
echo 清理旧的构建文件...
if exist "build" rmdir /s /q "build"
if exist "dist\零售通知工具" rmdir /s /q "dist\零售通知工具"

echo.
echo 正在打包...
pyinstaller "零售通知工具.spec"
if errorlevel 1 (
    echo 错误: 打包失败
    pause & exit /b 1
)

echo.
echo 复制数据文件...
if not exist "dist\零售通知工具\data" mkdir "dist\零售通知工具\data"
copy /Y "data\groups.json"    "dist\零售通知工具\data\" >nul
copy /Y "data\templates.json" "dist\零售通知工具\data\" >nul

echo.
echo ========================================
echo 打包完成！
echo 程序目录: dist\零售通知工具\
echo 入口文件: dist\零售通知工具\零售通知工具.exe
echo ========================================
pause