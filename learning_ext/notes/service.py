"""学习笔记与参考资料 service。"""

from __future__ import annotations

import io
import logging
import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import unquote, urlparse

from sqlmodel import Session, select

from learning_ext.db.models import (
    KnowledgeNode,
    LearningProject,
    NodeNote,
    NodeResource,
)
from learning_ext.llm import chat

logger = logging.getLogger(__name__)


# ==================== 笔记 ====================


def get_note(
    session: Session, node_id: int, user_id: str = "default"
) -> Optional[NodeNote]:
    """获取某知识点的笔记 (每节点一条)。"""
    return session.exec(
        select(NodeNote)
        .where(NodeNote.node_id == node_id)
        .where(NodeNote.user_id == user_id)
    ).first()


def save_note(
    session: Session,
    node_id: int,
    project_id: int,
    content: str,
    user_id: str = "default",
) -> NodeNote:
    """保存/更新笔记 (upsert)。"""
    note = get_note(session, node_id, user_id)
    if note:
        note.content = content
        note.updated_at = datetime.utcnow()
    else:
        note = NodeNote(
            user_id=user_id,
            node_id=node_id,
            project_id=project_id,
            content=content,
        )
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


# ==================== 参考资料 ====================


def get_resources(session: Session, node_id: int) -> List[NodeResource]:
    return session.exec(
        select(NodeResource)
        .where(NodeResource.node_id == node_id)
        .order_by(NodeResource.id)
    ).all()


def generate_resources(node: KnowledgeNode, project_topic: str) -> List[dict]:
    """AI 推荐正文实际用到的参考资料，并抓取 PDF/HTML 正文入库。"""
    prompt = f"""请根据下面这节课程正文，找出正文实际需要引用或支撑的参考资料。返回 JSON 数组，每项：
{{
  "title": "资料名称",
  "url": "可直接打开的 PDF 或 HTML 页面链接",
  "rtype": "pdf|html|doc|article|tool",
  "reference_for": "这份资料对应课程正文的哪一节/哪一部分，例如 ## LoRA 原理",
  "description": "它支撑正文里的哪个概念、公式、流程或代码 (1句)"
}}

【学习主题】{project_topic}
【知识点】{node.title} ({node.code})
【课程正文】
{(node.description or "")[:5000]}

规则：
- 只推荐正文会用到的资料，不要泛泛推荐延伸阅读
- 有 PDF 论文、白皮书、官方 PDF 时优先 PDF；没有 PDF 再给 HTML 文档或文章
- 不要返回搜索结果页、视频站首页、书籍购买页、需要登录的页面
- 资料要真实存在，不要编造
- 只返回 JSON 数组"""
    from learning_ext.llm import chat_json

    result = chat_json(prompt)
    if isinstance(result, list):
        candidates = result
    else:
        candidates = result.get("resources", []) if isinstance(result, dict) else []

    fetched_resources: list[dict] = []
    for item in candidates[:6]:
        url = str(item.get("url", "")).strip()
        if not _is_fetchable_url(url):
            continue
        fetched = fetch_resource_content(url)
        fetched_format = fetched.get("format") or _resource_format_from_url(url)
        rtype = _normalize_resource_type(item.get("rtype"), fetched_format)
        reference_for = (
            item.get("reference_for")
            or item.get("section")
            or item.get("used_for")
            or "本节相关内容"
        )
        note = str(item.get("description", "")).strip()
        description = _build_resource_description(
            reference_for=reference_for,
            note=note,
            fetched=fetched,
        )
        resource = {
            "title": fetched.get("title") or item.get("title", ""),
            "url": fetched.get("url") or url,
            "rtype": rtype,
            "description": description,
            "preview": fetched.get("content", ""),
            "fetch_status": fetched.get("status", ""),
        }
        fetched_resources.append(resource)

    return fetched_resources


def save_resources_to_db(
    session: Session, node_id: int, project_id: int, resources: List[dict]
) -> List[NodeResource]:
    """把 AI 生成的参考资料存库 (替换旧的)。"""
    # 清理旧 AI 资源
    old = session.exec(
        select(NodeResource)
        .where(NodeResource.node_id == node_id)
        .where(NodeResource.source == "ai")
    ).all()
    for r in old:
        session.delete(r)
    created = []
    for item in resources:
        r = NodeResource(
            node_id=node_id,
            project_id=project_id,
            title=item.get("title", ""),
            url=item.get("url", ""),
            rtype=item.get("rtype", "doc"),
            description=item.get("description", ""),
            preview=item.get("preview", ""),
            source="ai",
        )
        session.add(r)
        created.append(r)
    session.commit()
    return created


def _is_fetchable_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _resource_format_from_url(url: str) -> str:
    path = urlparse(url).path.lower()
    if path.endswith(".pdf"):
        return "pdf"
    return "html"


def _normalize_resource_type(raw_type, fetched_format: str) -> str:
    rtype = str(raw_type or "").strip().lower()
    if fetched_format == "pdf":
        return "pdf"
    if fetched_format in {"html", "text"}:
        return "html"
    return rtype or "html"


def _build_resource_description(reference_for: str, note: str, fetched: dict) -> str:
    lines = [f"参考位置：{str(reference_for).strip() or '本节相关内容'}"]
    if note:
        lines.append(f"说明：{note}")
    if fetched.get("ok"):
        fmt = str(fetched.get("format") or "").upper() or "HTML"
        lines.append(f"抓取状态：已拉取 {fmt} 正文")
    else:
        lines.append(f"抓取状态：失败 - {fetched.get('error', '正文过短或不可读')}")
    return "\n".join(lines)


def _extract_text_from_html(html: str) -> tuple[str, str]:
    """Extract a page title and readable text from HTML."""
    title = ""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        for tag in soup(
            [
                "script",
                "style",
                "noscript",
                "svg",
                "nav",
                "footer",
                "header",
                "form",
                "aside",
            ]
        ):
            tag.decompose()
        main = soup.find("main") or soup.find("article") or soup.body or soup
        text = main.get_text("\n", strip=True)
    except Exception:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
        text = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.I)
        text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.I)
        text = re.sub(r"<[^>]+>", "\n", text)

    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return title, text


def _charset_from_content_type(content_type: str) -> Optional[str]:
    match = re.search(r"charset=([A-Za-z0-9._-]+)", content_type or "", re.I)
    return match.group(1) if match else None


def _charset_from_html_meta(content: bytes) -> Optional[str]:
    head = content[:4096]
    match = re.search(
        rb"<meta[^>]+charset=[\"']?\s*([A-Za-z0-9._-]+)",
        head,
        re.I,
    )
    if match:
        return match.group(1).decode("ascii", errors="ignore")
    return None


def _decode_response_text(resp) -> str:
    content = getattr(resp, "content", b"") or b""
    if not content:
        return getattr(resp, "text", "") or ""
    encodings = [
        _charset_from_html_meta(content),
        _charset_from_content_type(resp.headers.get("content-type", "")),
        getattr(resp, "encoding", None),
        getattr(resp, "apparent_encoding", None),
        "utf-8",
    ]
    tried = set()
    for encoding in encodings:
        if not encoding:
            continue
        normalized = str(encoding).strip()
        if not normalized or normalized.lower() in tried:
            continue
        tried.add(normalized.lower())
        try:
            return content.decode(normalized)
        except (LookupError, UnicodeDecodeError):
            continue
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(content).best()
        if best is not None:
            return str(best)
    except Exception:
        pass
    return content.decode("utf-8", errors="replace")


def _title_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    name = path.rsplit("/", 1)[-1] if path else ""
    return unquote(name) or url


def _extract_pdf_text(content: bytes, *, max_chars: int = 12000) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    chunks = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            chunks.append(text.strip())
        if sum(len(chunk) for chunk in chunks) >= max_chars:
            break
    return "\n\n".join(chunks)[:max_chars]


def fetch_resource_content(url: str, *, max_chars: int = 12000) -> dict:
    """Fetch a resource URL and return extracted readable text."""
    if not _is_fetchable_url(url):
        return {"ok": False, "url": url, "error": "不是可抓取的 HTTP/HTTPS 链接"}
    try:
        import requests

        resp = requests.get(
            url,
            timeout=18,
            allow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
            },
        )
        if resp.status_code != 200:
            return {
                "ok": False,
                "url": resp.url or url,
                "status": resp.status_code,
                "error": f"HTTP {resp.status_code}",
            }

        content_type = resp.headers.get("content-type", "").lower()
        is_pdf = "application/pdf" in content_type or urlparse(
            resp.url or url
        ).path.lower().endswith(".pdf")
        if is_pdf:
            title = _title_from_url(resp.url or url)
            text = _extract_pdf_text(resp.content, max_chars=max_chars)
            text = re.sub(r"\s+\n", "\n", text).strip()
            if len(text) < 50:
                return {
                    "ok": False,
                    "title": title,
                    "url": resp.url or url,
                    "status": resp.status_code,
                    "format": "pdf",
                    "content": text,
                    "error": "PDF 未提取到足够正文",
                }
            return {
                "ok": True,
                "title": title,
                "url": resp.url or url,
                "status": resp.status_code,
                "format": "pdf",
                "content": text[:max_chars],
            }

        decoded_text = _decode_response_text(resp)
        if "text/plain" in content_type:
            title = urlparse(resp.url).path.rsplit("/", 1)[-1] or resp.url
            text = decoded_text
            fmt = "text"
        elif "html" in content_type or not content_type:
            title, text = _extract_text_from_html(decoded_text)
            fmt = "html"
        else:
            return {
                "ok": False,
                "url": resp.url or url,
                "status": resp.status_code,
                "format": "unknown",
                "error": f"暂不支持抓取该内容类型：{content_type or 'unknown'}",
            }

        text = re.sub(r"\s+\n", "\n", text).strip()
        if len(text) < 200:
            return {
                "ok": False,
                "title": title,
                "url": resp.url or url,
                "status": resp.status_code,
                "format": fmt,
                "content": text,
                "error": "页面正文过短，可能需要登录或主要内容由脚本渲染",
            }
        return {
            "ok": True,
            "title": title or resp.url or url,
            "url": resp.url or url,
            "status": resp.status_code,
            "format": fmt,
            "content": text[:max_chars],
        }
    except Exception as e:
        return {"ok": False, "url": url, "error": str(e)}


def fetch_preview(url: str) -> str:
    """抓取 URL 内容作为预览 (简单版: 尝试请求并提取文本)。"""
    fetched = fetch_resource_content(url, max_chars=3000)
    if not fetched.get("ok"):
        return f"*预览失败: {fetched.get('error', '无法抓取')}*"
    return (
        f"## {fetched.get('title')}\n\n"
        f"来源: `{fetched.get('url')}`\n\n"
        f"{fetched.get('content', '')[:3000]}..."
    )


# ==================== 划词 AI 解释 ====================


def explain_term(term: str, node: KnowledgeNode, project_topic: str) -> str:
    """AI 解释选中名词 (快速术语解释, 区别于追问)。"""
    prompt = f"""学习者正在学习「{project_topic}」的「{node.title}」这一节。
阅读教学内容时，遇到了一个不懂的名词/术语：**{term}**

请简洁地解释这个名词：
1. 它是什么 (1-2句直白解释)
2. 在当前学习背景下它为什么重要 / 怎么用 (1-2句)
3. 举一个通俗的例子 (如果适用)

用 Markdown，**控制在 200 字以内**。直接给解释，不要前言。"""
    return chat(
        prompt,
        system="你是术语词典 + 耐心导师, 擅长用最简单的话解释专业名词。",
        temperature=0.3,
        max_tokens=500,
    )
