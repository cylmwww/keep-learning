@echo off
chcp 65001 >nul
title Keep Learning
cd /d "%~dp0"
echo Keep Learning 启动中... (首次约 90 秒，请稍候)
echo.
kotaemon\.venv\Scripts\python.exe launcher.py
pause
