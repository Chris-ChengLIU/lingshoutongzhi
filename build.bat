@echo off
chcp 65001 >nul
echo ========================================
echo 零售通知自动分发工具 - 打包脚本
echo ========================================
echo.

set VENV_PATH=venv\Scripts

%VENV_PATH%\python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到Python，请先安装Python
    pause & exit /b 1
)

REM echo 正在安装依赖...
REM %VENV_PATH%\pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
REM if errorlevel 1 (
REM     echo 错误: 安装依赖失败
REM     pause & exit /b 1
REM )

echo.
echo 清理旧的构建文件...
if exist "build" rmdir /s /q "build"
if exist "dist\RetailNotifier" rmdir /s /q "dist\RetailNotifier"

echo.
echo 正在打包...
%VENV_PATH%\pyinstaller "零售通知工具.spec"
if errorlevel 1 (
    echo 错误: 打包失败
    pause & exit /b 1
)

REM 打包清单（零售通知工具.spec）已内置 data\templates.json 与 models\ ，
REM 此处不再手工拷贝 data\ —— 否则会把打包机的 groups.json/auth.json 等运行时状态带进包。

echo.
echo 检查 OCR 模型...
if not exist "models\ch_PP-OCRv4_det_infer\inference.pdmodel" (
    echo 未找到 OCR 模型，开始下载（约 18MB，需联网）...
    powershell -NoProfile -ExecutionPolicy Bypass -File "download_models.ps1"
    if errorlevel 1 (
        echo 错误: OCR 模型下载失败
        pause & exit /b 1
    )
)
echo OCR 模型就绪。

echo.
echo ========================================
echo 打包完成！
echo 程序目录: dist\RetailNotifier\
echo 入口文件: dist\RetailNotifier\零售通知工具.exe
echo ========================================
pause