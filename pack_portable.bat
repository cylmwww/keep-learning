@echo off
chcp 65001 >nul
title Keep Learning - 组装便携版

cd /d "%~dp0"

echo ============================================================
echo   Keep Learning - 组装可分发的便携版
echo ============================================================
echo.

REM 1. 先确保 exe 已打包
if not exist "dist\KeepLearning\KeepLearning.exe" (
    echo [!] 未找到打包好的 exe，先执行 build_exe.bat
    call build_exe.bat
)

REM 2. 组装便携版目录
set PORTABLE=dist\KeepLearning-Portable
echo [1/4] 清理旧的便携版目录...
if exist "%PORTABLE%" rmdir /s /q "%PORTABLE%"

echo [2/4] 复制 exe 和运行时...
mkdir "%PORTABLE%"
xcopy /E /I /Y "dist\KeepLearning\*" "%PORTABLE%\" >nul

echo [3/4] 复制 Keep Learning 代码...
copy /Y custom_app.py "%PORTABLE%\" >nul
xcopy /E /I /Y learning_ext "%PORTABLE%\learning_ext" >nul
copy /Y README.md "%PORTABLE%\" >nul

echo [4/4] 复制 Kotaemon 运行时 (venv，体积较大，请耐心等待)...
xcopy /E /I /Y "kotaemon\.venv" "%PORTABLE%\kotaemon\.venv" >nul
REM 复制 Kotaemon 必需的非 venv 文件
copy /Y "kotaemon\flowsettings.py" "%PORTABLE%\kotaemon\" >nul
copy /Y "kotaemon\app.py" "%PORTABLE%\kotaemon\" >nul
xcopy /E /I /Y "kotaemon\libs" "%PORTABLE%\kotaemon\libs" >nul
if exist "kotaemon\templates" xcopy /E /I /Y "kotaemon\templates" "%PORTABLE%\kotaemon\templates" >nul

echo.
echo ============================================================
echo   便携版组装完成！
echo   位置: %PORTABLE%
echo.
echo   分发方式:
echo     把整个 KeepLearning-Portable 文件夹打包成 zip 即可分发
echo     用户解压后双击 KeepLearning.exe 直接运行 (首次需配 LLM key)
echo ============================================================
echo.
echo 提示: 便携版体积较大 (因含完整 Python venv)。
echo       如需更小体积，可去掉 venv，让用户首次运行 setup.bat 联网安装。
pause
