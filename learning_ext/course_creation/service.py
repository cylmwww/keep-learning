from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from sqlmodel import Session, select

from learning_ext.course_creation.prompts import (
    BLUEPRINT_SYSTEM,
    LESSON_SYSTEM,
    REFINE_BLUEPRINT_SYSTEM,
    RESEARCH_SYSTEM,
)
from learning_ext.db.models import (
    CourseDraft,
    CourseSource,
    KnowledgeNode,
    LessonContentRevision,
)
from learning_ext.llm import chat, chat_json
from learning_ext.path_generator.service import save_roadmap
from learning_ext.progress.study import course_code_sort_key


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _load(value: str, default):
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return default


def _owned_draft(session: Session, draft_id: int, owner_id: str) -> CourseDraft:
    draft = session.get(CourseDraft, int(draft_id))
    if draft is None or draft.owner_id != owner_id:
        raise ValueError("课程草稿不存在或无权访问")
    return draft


def extract_material(session: Session, file_path: str | None) -> tuple[str, str]:
    if not file_path:
        return "", ""
    path = Path(file_path)
    if not path.is_file():
        raise ValueError("教材文件不存在")
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("单个教材不能超过 20 MB")
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown"}:
        text = path.read_text(encoding="utf-8", errors="replace")
    elif suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        if len(reader.pages) > 1000:
            raise ValueError("教材超过 1000 页，请拆分后上传")
        parts = []
        for number, page in enumerate(reader.pages, 1):
            content = (page.extract_text() or "").strip()
            if content:
                parts.append(f"[第 {number} 页]\n{content}")
        text = "\n\n".join(parts)
    elif suffix == ".docx":
        from docx import Document

        doc = Document(str(path))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    else:
        raise ValueError("当前支持 PDF、DOCX、TXT 和 Markdown 教材")
    text = text.strip()
    if len(text) < 80:
        raise ValueError("未能从教材提取足够文字；扫描版 PDF 暂不支持 OCR")
    return path.name, text[:200000]


def create_draft(
    session: Session,
    owner_id: str,
    input_text: str,
    material_name: str = "",
    material_text: str = "",
) -> CourseDraft:
    if not (input_text or "").strip() and not (material_text or "").strip():
        raise ValueError("请输入想学习的内容，或上传教材")
    draft = CourseDraft(
        owner_id=owner_id,
        input_text=(input_text or "").strip(),
        material_name=material_name,
        material_text=material_text,
        status="researching",
    )
    session.add(draft)
    session.commit()
    session.refresh(draft)
    if material_text:
        session.add(
            CourseSource(
                draft_id=draft.id,
                owner_id=owner_id,
                source_type="material",
                title=material_name or "用户教材",
                locator="上传教材",
                excerpt=material_text[:4000],
                read_status="full",
            )
        )
        session.commit()
    return draft


def _search_web(query: str, limit: int = 4) -> list[dict]:
    import requests

    response = requests.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        headers={"User-Agent": "KeepLearning/2.0 (+local course research)"},
        timeout=(8, 15),
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    body = response.text
    links = re.findall(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', body, re.I | re.S
    )
    snippets = re.findall(
        r'class="result__snippet"[^>]*>(.*?)</(?:a|div)>', body, re.I | re.S
    )
    results = []
    for index, (raw_url, raw_title) in enumerate(links[:limit]):
        url = html.unescape(raw_url)
        parsed = urlparse(url)
        if parsed.netloc.endswith("duckduckgo.com"):
            url = unquote(parse_qs(parsed.query).get("uddg", [url])[0])
        if urlparse(url).scheme not in {"http", "https"}:
            continue
        title = re.sub(r"<[^>]+>", "", html.unescape(raw_title)).strip()
        snippet = snippets[index] if index < len(snippets) else ""
        snippet = re.sub(r"<[^>]+>", "", html.unescape(snippet)).strip()
        results.append({"title": title or url, "url": url, "excerpt": snippet})
    return results


def run_research(session: Session, draft_id: int, owner_id: str = "default") -> dict:
    draft = _owned_draft(session, draft_id, owner_id)
    query_seed = draft.input_text or draft.material_name or draft.material_text[:200]
    query_result = chat_json(
        f"为课程调研生成 3 个简短、互补的中文网络搜索词。主题：{query_seed}\n只返回 {{\"queries\":[...]}}",
        system="你负责设计可验证的课程资料搜索词，只返回 JSON。",
    )
    queries = [str(q).strip() for q in query_result.get("queries", []) if str(q).strip()][:3]
    if not queries:
        queries = [query_seed[:120]]
    web_sources = []
    search_errors = []
    for query in queries:
        try:
            web_sources.extend(_search_web(query))
        except Exception as exc:
            search_errors.append(f"{query}: {type(exc).__name__}")
    seen = set()
    unique_sources = []
    for source in web_sources:
        key = source["url"].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        unique_sources.append(source)
    for source in unique_sources[:10]:
        session.add(
            CourseSource(
                draft_id=draft.id,
                owner_id=owner_id,
                source_type="web",
                title=source["title"][:500],
                url=source["url"][:2000],
                excerpt=source["excerpt"][:4000],
                read_status="summary",
            )
        )
    evidence = {
        "user_input": draft.input_text,
        "material_name": draft.material_name,
        "material_excerpt": draft.material_text[:16000],
        "queries": queries,
        "web_sources": unique_sources[:10],
        "search_errors": search_errors,
    }
    result = chat_json(
        "请形成调研简报和学习者问卷：\n" + json.dumps(evidence, ensure_ascii=False),
        system=RESEARCH_SYSTEM,
    )
    result = _normalize_research(result, queries, unique_sources, search_errors)
    draft.research_json = _dump(result)
    draft.questionnaire_json = _dump({"questions": result["questions"]})
    draft.status = "awaiting_answers"
    draft.revision += 1
    draft.updated_at = datetime.utcnow()
    session.add(draft)
    session.commit()
    return result


def _normalize_research(result, queries, sources, errors) -> dict:
    if not isinstance(result, dict):
        raise ValueError("调研模型返回格式无效")
    questions = result.get("questions")
    if not isinstance(questions, list) or not 4 <= len(questions) <= 6:
        raise ValueError("调研问卷必须包含 4-6 个问题")
    normalized = []
    for index, question in enumerate(questions, 1):
        options = question.get("options") if isinstance(question, dict) else None
        if not isinstance(options, list) or len(options) < 2:
            raise ValueError(f"第 {index} 个问题缺少有效选项")
        normalized.append(
            {
                "id": str(question.get("id") or f"q{index}"),
                "title": str(question.get("title") or f"问题 {index}"),
                "reason": str(question.get("reason") or "用于调整课程内容与难度"),
                "type": "multiple" if question.get("type") == "multiple" else "single",
                "options": [
                    {
                        "value": str(option.get("value") or f"option_{i}"),
                        "label": str(option.get("label") or option.get("value") or f"选项 {i}"),
                        "description": str(option.get("description") or ""),
                    }
                    for i, option in enumerate(options, 1)
                    if isinstance(option, dict)
                ],
            }
        )
    return {
        "summary": str(result.get("summary") or "已完成初步课程调研。"),
        "topic": str(result.get("topic") or "待创建课程"),
        "core_areas": [str(v) for v in result.get("core_areas", [])],
        "prerequisites": [str(v) for v in result.get("prerequisites", [])],
        "suggested_extensions": [str(v) for v in result.get("suggested_extensions", [])],
        "questions": normalized,
        "queries": queries,
        "sources": sources,
        "search_errors": errors,
    }


def build_blueprint(
    session: Session,
    draft_id: int,
    answers: dict,
    owner_id: str = "default",
) -> dict:
    draft = _owned_draft(session, draft_id, owner_id)
    questionnaire = _load(draft.questionnaire_json, {})
    questions = questionnaire.get("questions", [])
    missing = [q["id"] for q in questions if not answers.get(q["id"])]
    if missing:
        raise ValueError("请完成所有问题后再生成课程蓝图")
    payload = {
        "input": draft.input_text,
        "material_name": draft.material_name,
        "research": _load(draft.research_json, {}),
        "answers": answers,
    }
    blueprint = chat_json(
        "请生成课程蓝图：\n" + json.dumps(payload, ensure_ascii=False),
        system=BLUEPRINT_SYSTEM,
    )
    _validate_blueprint(blueprint)
    draft.answers_json = _dump(answers)
    draft.blueprint_json = _dump(blueprint)
    draft.preview_json = "{}"
    draft.status = "awaiting_blueprint_confirmation"
    draft.revision += 1
    draft.updated_at = datetime.utcnow()
    session.add(draft)
    session.commit()
    return blueprint


def refine_blueprint(
    session: Session,
    draft_id: int,
    instruction: str,
    owner_id: str = "default",
) -> dict:
    if not (instruction or "").strip():
        raise ValueError("请输入希望调整的内容")
    draft = _owned_draft(session, draft_id, owner_id)
    current = _load(draft.blueprint_json, {})
    if not current:
        raise ValueError("请先生成课程蓝图")
    result = chat_json(
        f"【现有蓝图】\n{json.dumps(current, ensure_ascii=False)}\n\n【调整意见】\n{instruction.strip()}",
        system=REFINE_BLUEPRINT_SYSTEM,
    )
    _validate_blueprint(result)
    draft.blueprint_json = _dump(result)
    draft.preview_json = "{}"
    draft.status = "awaiting_blueprint_confirmation"
    draft.revision += 1
    draft.updated_at = datetime.utcnow()
    session.add(draft)
    session.commit()
    return result


def _flatten_lessons(blueprint: dict) -> list[dict]:
    lessons = []
    for unit_index, unit in enumerate(blueprint.get("units", []), 1):
        for lecture_index, lecture in enumerate(unit.get("lectures", []), 1):
            for lesson_index, lesson in enumerate(lecture.get("lessons", []), 1):
                item = dict(lesson)
                item["unit_title"] = str(unit.get("title") or f"单元 {unit_index}")
                item["lecture_title"] = str(lecture.get("title") or f"讲次 {lecture_index}")
                item.setdefault("code", f"{unit_index}.{lecture_index}.{lesson_index}")
                lessons.append(item)
    return lessons


def _validate_blueprint(blueprint: dict) -> None:
    if not isinstance(blueprint, dict) or not isinstance(blueprint.get("units"), list):
        raise ValueError("课程蓝图格式无效")
    lessons = _flatten_lessons(blueprint)
    if not lessons:
        raise ValueError("课程蓝图至少需要一个课节")
    codes = [str(item.get("code") or "") for item in lessons]
    if any(not code for code in codes) or len(codes) != len(set(codes)):
        raise ValueError("课程蓝图的课节编号为空或重复")
    known = set()
    for item in lessons:
        prereqs = [str(value) for value in item.get("prerequisites", [])]
        if any(value not in known for value in prereqs):
            raise ValueError(f"课节 {item['code']} 引用了不存在或尚未出现的前置课节")
        known.add(str(item["code"]))


def generate_preview(
    session: Session, draft_id: int, owner_id: str = "default"
) -> list[dict]:
    draft = _owned_draft(session, draft_id, owner_id)
    blueprint = _load(draft.blueprint_json, {})
    _validate_blueprint(blueprint)
    lessons = _flatten_lessons(blueprint)[:3]
    context = {
        "research": _load(draft.research_json, {}),
        "answers": _load(draft.answers_json, {}),
        "course": {"title": blueprint.get("title"), "summary": blueprint.get("summary")},
    }
    preview = []
    for lesson in lessons:
        content = chat(
            "请撰写这一课节：\n"
            + json.dumps({"context": context, "lesson": lesson}, ensure_ascii=False),
            system=LESSON_SYSTEM,
            max_tokens=3500,
        )
        if not isinstance(content, str) or len(content.strip()) < 200:
            raise ValueError(f"课节 {lesson['code']} 的预览内容不完整")
        preview.append({"code": lesson["code"], "title": lesson.get("title", ""), "content": content})
    draft.preview_json = _dump({"blueprint_revision": draft.revision, "lessons": preview})
    draft.status = "awaiting_course_confirmation"
    draft.revision += 1
    draft.updated_at = datetime.utcnow()
    session.add(draft)
    session.commit()
    return preview


def _blueprint_to_roadmap(blueprint: dict) -> dict:
    lessons = _flatten_lessons(blueprint)
    unit_names = []
    for lesson in lessons:
        if lesson["unit_title"] not in unit_names:
            unit_names.append(lesson["unit_title"])
    stage_values = ["base", "strengthen", "sprint"]
    unit_stage = {
        name: stage_values[min(index, len(stage_values) - 1)]
        for index, name in enumerate(unit_names)
    }
    return {
        "summary": str(blueprint.get("summary") or blueprint.get("title") or "课程"),
        "stages": [
            {"name": name, "stage": unit_stage[name], "goal": name} for name in unit_names
        ],
        "nodes": [
            {
                "code": str(lesson["code"]),
                "title": str(lesson.get("title") or "未命名课节"),
                "description": str(lesson.get("objective") or ""),
                "stage": unit_stage[lesson["unit_title"]],
                "est_hours": max(float(lesson.get("minutes") or 45) / 60, 0.25),
                "difficulty": max(1, min(5, int(lesson.get("difficulty") or 3))),
                "prerequisites": [str(v) for v in lesson.get("prerequisites", [])],
            }
            for lesson in lessons
        ],
    }


def publish_course(
    session: Session, draft_id: int, owner_id: str = "default"
) -> int:
    draft = _owned_draft(session, draft_id, owner_id)
    if draft.published_project_id:
        return draft.published_project_id
    blueprint = _load(draft.blueprint_json, {})
    preview_data = _load(draft.preview_json, {})
    preview = preview_data.get("lessons", [])
    lessons = _flatten_lessons(blueprint)
    if len(preview) != min(3, len(lessons)):
        raise ValueError("前三节预览尚未全部生成")
    if preview_data.get("blueprint_revision") != draft.revision - 1:
        raise ValueError("课程蓝图已经变化，请重新生成预览")
    research = _load(draft.research_json, {})
    answers = _load(draft.answers_json, {})
    answer_labels = []
    for question in research.get("questions", []):
        selected = set(answers.get(question.get("id"), []))
        labels = [
            str(option.get("label") or option.get("value"))
            for option in question.get("options", [])
            if option.get("value") in selected
        ]
        if labels:
            answer_labels.append(f"{question.get('title', '学习者情况')}：{'、'.join(labels)}")
    roadmap = _blueprint_to_roadmap(blueprint)
    project = save_roadmap(
        session=session,
        user_id=owner_id,
        topic=draft.input_text or research.get("topic") or blueprint.get("title") or "课程",
        background="；".join(answer_labels),
        goal=str(blueprint.get("summary") or ""),
        weekly_hours=10.0,
        roadmap=roadmap,
        title=str(blueprint.get("title") or "未命名课程"),
        commit=False,
    )
    project.course_blueprint_json = _dump(blueprint)
    session.add(project)
    by_code = {item["code"]: item for item in preview}
    nodes = session.exec(
        select(KnowledgeNode).where(KnowledgeNode.project_id == project.id)
    ).all()
    for node in nodes:
        if node.code not in by_code:
            continue
        content = by_code[node.code]["content"]
        node.description = content
        session.add(node)
        session.add(
            LessonContentRevision(
                owner_id=owner_id,
                project_id=project.id,
                node_id=node.id,
                content=content,
                input_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            )
        )
    draft.published_project_id = project.id
    draft.status = "published"
    draft.updated_at = datetime.utcnow()
    session.add(draft)
    session.commit()
    return project.id


def get_ordered_lessons(blueprint: dict) -> list[dict]:
    return sorted(_flatten_lessons(blueprint), key=lambda item: course_code_sort_key(item["code"]))
