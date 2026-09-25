@echo off
chcp 65001 >nul
title Keep Learning

cd /d "%~dp0"

REM 优先用打包的 exe 同目录 python (如果存在便携版 python)
if exist "%~dp0python\python.exe" (
    "%~dp0python\python.exe" "%~dp0launcher.py"
) else (
    REM 用 Kotaemon venv 的 python 跑 launcher
    "%~dp0kotaemon\.venv\Scripts\python.exe" "%~dp0launcher.py"
)

if errorlevel 1 pause
