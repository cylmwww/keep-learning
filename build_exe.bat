@echo off
chcp 65001 >nul
title Keep Learning - 打包 exe

cd /d "%~dp0"

echo ============================================================
echo   Keep Learning - 打包 launcher.exe
echo   (便携版核心，只含启动逻辑 + PyWebView)
echo ============================================================
echo.

set PYINSTALLER=kotaemon\.venv\Scripts\pyinstaller.exe

if not exist "%PYINSTALLER%" (
    echo [错误] 未找到 PyInstaller，请先运行 setup.bat
    pause
    exit /b 1
)

echo [1/2] 清理旧产物...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo [2/2] PyInstaller 打包中 (约 1-3 分钟)...
"%PYINSTALLER%" ^
    --noconfirm ^
    --clean ^
    --onedir ^
    --windowed ^
    --name "KeepLearning" ^
    --version-file "version_info.txt" ^
    --hidden-import "webview" ^
    --hidden-import "webview.platforms.edgechromium" ^
    --collect-submodules "webview" ^
    --distpath dist ^
    --workpath build ^
    --specpath build ^
    launcher.py

if errorlevel 1 (
    echo.
    echo [错误] 打包失败，请查看上方日志
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   打包成功！
echo   产物: dist\KeepLearning\KeepLearning.exe
echo.
echo   便携版组装:
echo     1. 复制 dist\KeepLearning\ 下的所有文件到分发目录
echo     2. 把 custom_app.py、learning_ext\、kotaemon\.venv\ 一并复制
echo     3. 双击 KeepLearning.exe 即可运行
echo ============================================================
pause
