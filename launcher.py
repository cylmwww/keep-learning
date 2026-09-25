"""Keep Learning - Windows 桌面启动器。

职责：
    1. 定位 Kotaemon venv 和项目根目录
    2. 设置环境变量 (Python 路径、cohere 占位等)
    3. 启动 LearningApp 的 Gradio 服务 (后台线程，非阻塞)
    4. 主线程用 PyWebView 打开桌面窗口 (可选，环境无 pywebview 则退化为浏览器)

使用：
    直接双击运行，或被 run.bat / PyInstaller 打包的 exe 调用。
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("learning-launcher")


class _SafeStream:
    """包装 stdout，遇 GBK 无法编码的字符降级为 ASCII，避免 Windows 控制台崩溃"""

    def __init__(self, stream):
        self._stream = stream

    def write(self, text):
        try:
            self._stream.write(text)
        except UnicodeEncodeError:
            self._stream.write(text.encode("ascii", "replace").decode("ascii"))

    def flush(self):
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


sys.stdout = _SafeStream(sys.stdout)
sys.stderr = _SafeStream(sys.stderr)

# ------------------------------------------------------------------
# 路径定位 (支持源码运行和 PyInstaller 打包后运行)
# ------------------------------------------------------------------
if getattr(sys, "frozen", False):
    # PyInstaller 打包后：exe 所在目录
    BASE_DIR = Path(sys.executable).parent.resolve()
    _MEIPASS = Path(sys._MEIPASS)  # type: ignore
else:
    BASE_DIR = Path(__file__).parent.resolve()
    _MEIPASS = BASE_DIR

KOTAEMON_DIR = BASE_DIR / "kotaemon"
VENV_PYTHON = KOTAEMON_DIR / ".venv" / "Scripts" / "python.exe"
CUSTOM_APP = BASE_DIR / "custom_app.py"

PORT = 7860
HOST = "127.0.0.1"


def is_venv_ready() -> bool:
    return VENV_PYTHON.exists()


def ensure_venv() -> None:
    """检查 venv 是否就绪，否则提示用户运行 setup.bat"""
    if is_venv_ready():
        return
    log.error("=" * 60)
    log.error("Kotaemon 运行环境未就绪！")
    log.error(f"未找到: {VENV_PYTHON}")
    log.error("请先运行 setup.bat 初始化环境 (首次使用需要联网安装依赖)")
    log.error("=" * 60)
    input("按回车键退出...")
    sys.exit(1)


def find_free_port(default: int = 7860) -> int:
    """7860 被占用则找空闲端口"""
    for port in range(default, default + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, port))
                return port
            except OSError:
                continue
    return default


def wait_for_server(port: int, timeout: int = 120) -> bool:
    """等待 Gradio 服务就绪"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((HOST, port), timeout=2):
                return True
        except OSError:
            time.sleep(1)
    return False


def start_gradio_backend(port: int) -> subprocess.Popen:
    """以子进程启动 Gradio 后端 (custom_app.py)。

    用子进程而非线程，避免 Gradio/uvicorn 信号处理干扰主进程，
    也便于打包后隔离。
    """
    env = os.environ.copy()
    # 占位 key 避免 Kotaemon 初始化 cohere 等服务校验
    for k in ("COHERE_API_KEY", "VOYAGE_API_KEY", "MISTRAL_API_KEY", "GOOGLE_API_KEY"):
        env.setdefault(k, "placeholder-key-1234567890")
    env["GRADIO_SERVER_NAME"] = HOST
    env["GRADIO_SERVER_PORT"] = str(port)
    env["PYTHONPATH"] = str(BASE_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"

    log.info(f"启动后端: {VENV_PYTHON} {CUSTOM_APP}")
    proc = subprocess.Popen(
        [str(VENV_PYTHON), str(CUSTOM_APP)],
        cwd=str(KOTAEMON_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    # 后台线程转发后端日志
    def _log_pipe():
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    log.info(f"[backend] {line}")
        except Exception:
            pass

    threading.Thread(target=_log_pipe, daemon=True).start()
    return proc


def open_desktop_window(url: str) -> bool:
    """尝试用 PyWebView 打开桌面窗口，失败则降级到浏览器。

    Returns:
        True 如果用了桌面窗口 (主线程会被 pywebview 阻塞)
        False 如果降级到浏览器
    """
    try:
        import webview  # type: ignore

        log.info("使用 PyWebView 桌面窗口模式")
        webview.create_window(
            title="Keep Learning",
            url=url,
            width=1280,
            height=860,
            min_size=(1024, 700),
        )
        webview.start()
        return True
    except ImportError:
        log.info("未安装 pywebview，降级为浏览器模式")
        return False
    except Exception as e:
        log.warning(f"PyWebView 启动失败 ({e})，降级为浏览器模式")
        return False


def main():
    log.info("=" * 60)
    log.info("Keep Learning - 启动中")
    log.info("=" * 60)

    ensure_venv()

    port = find_free_port(PORT)
    if port != PORT:
        log.warning(f"端口 {PORT} 被占用，改用 {port}")

    # 启动 Gradio 后端
    proc = start_gradio_backend(port)
    log.info(f"等待后端就绪 (最多 180s)...")
    if not wait_for_server(port, timeout=180):
        log.error("后端启动超时，请查看上方日志")
        proc.terminate()
        input("按回车键退出...")
        sys.exit(1)

    url = f"http://{HOST}:{port}"
    log.info(f"[OK] 后端就绪: {url}")

    use_pywebview = os.environ.get("LE_DESKTOP", "1") != "0"

    if use_pywebview:
        if not open_desktop_window(url):
            webbrowser.open(url)
            log.info("PyWebView 不可用，已在浏览器打开。")
            try:
                proc.wait()
            except KeyboardInterrupt:
                proc.terminate()
        log.info("桌面窗口已关闭，正在停止后端...")
    else:
        webbrowser.open(url)
        log.info("已在浏览器打开 (http://127.0.0.1:7860)。关闭本窗口或 Ctrl+C 退出。")
        try:
            proc.wait()
        except KeyboardInterrupt:
            pass

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    log.info("已退出")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception(f"启动失败: {e}")
        input("按回车键退出...")
        sys.exit(1)
