"""极简模型配置页 - 替代 Kotaemon 复杂的 Resources 页。

用户只需：选服务商 → 填 API Key → 点保存。
后台自动填好 base_url / 模型名，并即时更新运行时 LLM 池。
"""

from __future__ import annotations

from urllib.parse import urlsplit
from pathlib import Path

import gradio as gr
from ktem.app import BasePage

# 预设服务商配置 (base_url, 对话模型, 向量模型, 备注)
PROVIDERS = {
    "DeepSeek (推荐，便宜好用)": {
        "base_url": "https://api.deepseek.com/v1",
        "chat_model": "deepseek-chat",
        "embed_model": "",
        "note": "DeepSeek 只有对话模型，无向量模型。配置后学习路线/测验/对话立即可用。上传资料问答(RAG)需另配向量模型。",
        "key_url": "https://platform.deepseek.com/api_keys",
    },
    "智谱 GLM (有免费额度)": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "chat_model": "glm-4-flash",
        "embed_model": "embedding-3",
        "note": "智谱有完整对话+向量模型，免费额度充足，RAG 全功能可用。",
        "key_url": "https://bigmodel.cn/console/usercenter/apikeys",
    },
    "通义千问 (阿里云)": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "chat_model": "qwen-plus",
        "embed_model": "text-embedding-v3",
        "note": "通义千问有完整对话+向量模型。",
        "key_url": "https://dashscope.console.aliyun.com/apiKey",
    },
    "OpenAI (官方)": {
        "base_url": "https://api.openai.com/v1",
        "chat_model": "gpt-4o-mini",
        "embed_model": "text-embedding-3-large",
        "note": "效果最好但需海外网络，成本较高。",
        "key_url": "https://platform.openai.com/api-keys",
    },
    "自定义 (OpenAI 兼容接口)": {
        "base_url": "",
        "chat_model": "",
        "embed_model": "",
        "note": "填入任意 OpenAI 兼容的接口。",
        "key_url": "",
    },
}

# .env 文件路径
ENV_FILE = Path(__file__).resolve().parent.parent.parent / "kotaemon" / ".env"


ENV_KEYS = {
    "base_url": "OPENAI_API_BASE",
    "api_key": "OPENAI_API_KEY",
    "chat_model": "OPENAI_CHAT_MODEL",
    "embed_base_url": "OPENAI_EMBEDDINGS_API_BASE",
    "embed_api_key": "OPENAI_EMBEDDINGS_API_KEY",
    "embed_model": "OPENAI_EMBEDDINGS_MODEL",
}


def _read_env() -> dict:
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    data = {field: values.get(key, "") for field, key in ENV_KEYS.items()}
    for field in ("api_key", "embed_api_key"):
        if "请在UI" in data[field] or "YOUR" in data[field]:
            data[field] = ""
    if data["embed_model"]:
        if ENV_KEYS["embed_base_url"] not in values:
            data["embed_base_url"] = data["base_url"]
        if ENV_KEYS["embed_api_key"] not in values:
            data["embed_api_key"] = data["api_key"]
    return data


def _write_env(updates: dict) -> None:
    if any("\n" in value or "\r" in value for value in updates.values()):
        raise ValueError("配置字段不能包含换行")
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    replacements = {ENV_KEYS[field]: value for field, value in updates.items()}
    written = set()
    result = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in replacements:
            if key not in written:
                result.append(f"{key}={replacements[key]}")
                written.add(key)
        else:
            result.append(line)
    result.extend(f"{key}={value}" for key, value in replacements.items() if key not in written)
    ENV_FILE.write_text("\n".join(result) + "\n", encoding="utf-8")


def _apply_to_runtime(kind: str, base_url: str, api_key: str, model: str) -> None:
    if kind == "chat":
        from ktem.llms.manager import llms as manager
        spec = {"__type__": "kotaemon.llms.ChatOpenAI", "temperature": 0.3}
    else:
        from ktem.embeddings.manager import embedding_models_manager as manager
        spec = {"__type__": "kotaemon.embeddings.OpenAIEmbeddings"}
    spec.update(base_url=base_url, api_key=api_key, model=model, timeout=60)
    if "openai" in manager:
        manager.update("openai", spec=spec, default=True)
    else:
        manager.add("openai", spec=spec, default=True)


def _validate(base_url, api_key, model):
    if not api_key or not model or not base_url:
        return "请填写接口地址、API Key 和模型名"
    if any("\n" in value or "\r" in value for value in (base_url, api_key, model)):
        return "配置字段不能包含换行"
    parsed = urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
        return "请输入有效的 HTTP(S) 接口地址，密钥请填写在 API Key 栏"
    return ""


def _save_model(kind, api_key, base_url, model):
    api_key, base_url, model = api_key.strip(), base_url.strip().rstrip("/"), model.strip()
    error = _validate(base_url, api_key, model)
    if error:
        return f"❌ {error}"
    if kind == "chat":
        current = _read_env()
        updates = {"base_url": base_url, "api_key": api_key, "chat_model": model}
        if current["embed_model"]:
            updates.update(embed_base_url=current["embed_base_url"], embed_api_key=current["embed_api_key"])
    else:
        updates = {"embed_base_url": base_url, "embed_api_key": api_key, "embed_model": model}
    try:
        _write_env(updates)
        if kind == "chat":
            from learning_ext.llm.client import invalidate_cache
            invalidate_cache()
    except Exception:
        return "❌ 配置文件保存失败，请检查文件写入权限后重试。"
    try:
        _apply_to_runtime(kind, base_url, api_key, model)
    except Exception:
        return "⚠️ 配置文件已保存，但运行时启用失败。请检查配置后重新保存；当前不能确认已生效。"
    return "✅ 配置已保存并启用。可点击测试连接验证服务是否可用。"


def _test_embedding(base_url, api_key, model):
    import requests

    try:
        response = requests.post(
            f"{base_url.rstrip('/')}/embeddings",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "input": "连接测试"},
            timeout=30,
        )
        if response.status_code != 200:
            return f"❌ HTTP {response.status_code}，请检查向量模型的地址、密钥和模型名。"
        vector = response.json()["data"][0]["embedding"]
        if not isinstance(vector, list) or not vector:
            return "❌ 接口未返回有效向量"
        return f"✅ 向量接口连接成功，返回 {len(vector)} 维向量。"
    except Exception:
        return "❌ 向量接口请求失败或返回格式无效，请检查配置及网络。"


def _test_llm(base_url: str, api_key: str, chat_model: str) -> tuple[str, str]:
    """发一个测试请求验证配置"""
    if not api_key or "请在UI" in api_key:
        return "❌ 未填 API Key", ""
    try:
        import requests

        resp = requests.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": chat_model,
                "messages": [{"role": "user", "content": "只回复两个字：你好"}],
                "max_tokens": 20,
                "temperature": 0,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"]
            return f"✅ 连接成功！模型回复：{content}", content
        else:
            err = resp.json().get("error", {}).get("message", resp.text[:200])
            return f"❌ HTTP {resp.status_code}: {err}", ""
    except Exception as e:
        return f"❌ 请求失败: {e}", ""


class QuickSetupPage(BasePage):
    def on_building_ui(self):
        gr.Markdown("# 模型配置")
        gr.Markdown("对话模型与向量模型可使用不同服务商，各自独立保存和测试。接口需兼容 OpenAI 格式。")
        current = _read_env()
        self.sections = {}
        with gr.Row():
            for kind, title, prefix, model_field in (
                ("chat", "对话模型", "", "chat_model"),
                ("embedding", "向量模型（资料检索 / RAG）", "embed_", "embed_model"),
            ):
                with gr.Column(min_width=320, variant="panel"):
                    gr.Markdown(f"### {title}")
                    choices = [name for name, cfg in PROVIDERS.items() if kind == "chat" or cfg["embed_model"] or not cfg["base_url"]]
                    selected = next((name for name in choices if PROVIDERS[name]["base_url"] == current[prefix + "base_url"]), choices[-1])
                    provider = gr.Dropdown(label="服务商", choices=choices, value=selected)
                    base = gr.Textbox(label="接口地址（Base URL）", value=current[prefix + "base_url"], lines=1)
                    key = gr.Textbox(label="API Key", value=current[prefix + "api_key"], type="password")
                    model = gr.Textbox(label="模型名", value=current[model_field], lines=1)
                    if kind == "embedding":
                        gr.Markdown("仅资料检索需要配置。更换向量模型后，已有资料可能需要重新索引。")
                    with gr.Row():
                        test = gr.Button("测试连接")
                        save = gr.Button("保存并启用", variant="primary")
                    result = gr.Markdown("")
                    self.sections[kind] = dict(provider=provider, base=base, key=key, model=model, test=test, save=save, result=result)

    def on_register_events(self):
        for kind, section in self.sections.items():
            def provider_change(name, model_kind=kind):
                cfg = PROVIDERS[name]
                field = "chat_model" if model_kind == "chat" else "embed_model"
                return cfg["base_url"], "", cfg[field], "服务商已切换，请填入对应密钥并保存。"

            def save_model(key, base, model, model_kind=kind):
                return _save_model(model_kind, key, base, model)

            def test_model(key, base, model, model_kind=kind):
                key, base, model = key.strip(), base.strip(), model.strip()
                error = _validate(base, key, model)
                if error:
                    return f"❌ {error}"
                if model_kind == "chat":
                    return _test_llm(base, key, model)[0]
                return _test_embedding(base, key, model)

            section["provider"].input(provider_change, [section["provider"]], [section["base"], section["key"], section["model"], section["result"]])
            inputs = [section["key"], section["base"], section["model"]]
            section["test"].click(test_model, inputs, [section["result"]])
            section["save"].click(save_model, inputs, [section["result"]])

    def as_gradio_component(self):
        return None
