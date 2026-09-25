"""Keep Learning 的启动入口。

替换 Kotaemon 默认的 app.py，使用 LearningApp 加载学习特化 Tab。
本地运行时通过 launcher.py 调用本文件。
"""

import os
import sys
from pathlib import Path

_no_proxy = os.environ.get("NO_PROXY", os.environ.get("no_proxy", ""))
os.environ["NO_PROXY"] = ",".join(filter(None, [_no_proxy, "127.0.0.1", "localhost", "::1"]))
os.environ["no_proxy"] = os.environ["NO_PROXY"]

# Kotaemon 底座实例化 cohere/voyage 等 LLM 时会直接读 os.environ 校验 key，
# 本地若未配置这些服务，注入占位值避免启动崩溃 (实际不使用这些服务)
os.environ.setdefault("COHERE_API_KEY", "placeholder-key-1234567890")
os.environ.setdefault("VOYAGE_API_KEY", "placeholder-key-1234567890")
os.environ.setdefault("MISTRAL_API_KEY", "placeholder-key-1234567890")
os.environ.setdefault("GOOGLE_API_KEY", "placeholder-key-1234567890")

# 离线模式：避免启动时访问 huggingface.co 超时 (国内网络)；
# 需要下载模型时用户可手动设这两个变量为 0
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
# NLTK 数据路径：指向 llama_index 自带的 nltk_cache，避免联网下载 stopwords/punkt
import sys as _sys  # noqa: E402

_NLTK_CACHE = os.path.join(
    os.path.dirname(_sys.executable),
    "..",
    "Lib",
    "site-packages",
    "llama_index",
    "core",
    "_static",
    "nltk_cache",
)
_NLTK_CACHE = os.path.normpath(_NLTK_CACHE)
if os.path.isdir(_NLTK_CACHE):
    os.environ["NLTK_DATA"] = _NLTK_CACHE

# 确保 learning_ext 在 import 路径中
_HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("TIKTOKEN_CACHE_DIR", os.path.join(_HERE, ".runtime", "tiktoken"))
sys.path.insert(0, _HERE)

# Kotaemon 的 control.py 用 `import flowsettings`，要求 kotaemon 目录在 sys.path
_KOTAEMON_DIR = os.path.join(_HERE, "kotaemon")
sys.path.insert(0, _KOTAEMON_DIR)

from learning_ext.runtime import configure_runtime  # noqa: E402

configure_runtime()

from theflow.settings import settings as flowsettings  # noqa: E402

KH_APP_DATA_DIR = getattr(flowsettings, "KH_APP_DATA_DIR", ".")
KH_GRADIO_SHARE = getattr(flowsettings, "KH_GRADIO_SHARE", False)
GRADIO_TEMP_DIR = os.getenv("GRADIO_TEMP_DIR", None)
if GRADIO_TEMP_DIR is None:
    GRADIO_TEMP_DIR = os.path.join(str(KH_APP_DATA_DIR), "gradio_tmp")
    os.environ["GRADIO_TEMP_DIR"] = GRADIO_TEMP_DIR

from learning_ext.app import LearningApp  # noqa: E402


def _patch_gradio_template_for_learning_assets():
    """Insert learning_ext browser assets into Gradio's initial HTML template."""
    try:
        import gradio.routes as gradio_routes  # noqa: WPS433
        from jinja2 import ChoiceLoader, DictLoader  # noqa: WPS433

        script_path = "learning_ext/assets/word_lookup.js"
        word_lookup_js = Path(_HERE, script_path).read_text(encoding="utf-8")
        script_tag = f"<script>\n{word_lookup_js}\n</script>"
        template_root = Path(gradio_routes.STATIC_TEMPLATE_LIB)
        overrides = {}
        for template_name in ("frontend/index.html", "frontend/share.html"):
            source = (template_root / template_name).read_text(encoding="utf-8")
            if script_path not in source:
                marker = '<script type="module" crossorigin src='
                if marker in source:
                    source = source.replace(marker, f"{script_tag}\n\t\t{marker}", 1)
                else:
                    source = source.replace("</head>", f"\t\t{script_tag}\n\t</head>", 1)
            overrides[template_name] = source

        original_loader = gradio_routes.templates.env.loader
        gradio_routes.templates.env.loader = ChoiceLoader(
            [DictLoader(overrides), original_loader]
        )
        gradio_routes.templates.env.cache.clear()
    except Exception as e:
        print(f"[learning_ext] word lookup template patch failed: {e}")


_patch_gradio_template_for_learning_assets()

app = LearningApp()
demo = app.make()
demo.queue().launch(
    favicon_path=app._favicon,
    inbrowser=False,
    prevent_thread_lock=False,
    allowed_paths=[
        "libs/ktem/ktem/assets",
        os.path.join(_HERE, "learning_ext", "assets"),
        GRADIO_TEMP_DIR,
    ],
    share=KH_GRADIO_SHARE,
)
