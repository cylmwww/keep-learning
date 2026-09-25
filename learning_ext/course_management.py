from __future__ import annotations

import json

from sqlmodel import Session, select

from learning_ext.db.models import (
    CourseDraft,
    CourseSource,
    KnowledgeNode,
    LearningProject,
)
from learning_ext.project_ops import delete_project


DRAFT_STATUS_LABELS = {
    "researching": ("资料调研", 15),
    "awaiting_answers": ("填写学习问卷", 35),
    "awaiting_blueprint_confirmation": ("确认课程蓝图", 70),
    "awaiting_course_confirmation": ("确认前三节预览", 90),
}

PROJECT_STATUS_LABELS = {
    "active": "学习中",
    "paused": "已暂停",
    "completed": "已完成",
    "archived": "已归档",
}


def _json(value: str) -> dict:
    try:
        result = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return result if isinstance(result, dict) else {}


def _draft_title(draft: CourseDraft) -> str:
    blueprint = _json(draft.blueprint_json)
    research = _json(draft.research_json)
    return str(
        blueprint.get("title")
        or research.get("topic")
        or draft.input_text
        or draft.material_name
        or f"未命名草稿 #{draft.id}"
    )


def course_management_snapshot(session: Session, owner_id: str = "default") -> dict:
    projects = list(
        session.exec(
            select(LearningProject)
            .where(LearningProject.user_id == owner_id)
            .order_by(LearningProject.updated_at.desc(), LearningProject.id.desc())
        ).all()
    )
    drafts = list(
        session.exec(
            select(CourseDraft)
            .where(CourseDraft.owner_id == owner_id)
            .where(CourseDraft.published_project_id.is_(None))
            .where(CourseDraft.status.notin_(["published", "archived"]))
            .order_by(CourseDraft.updated_at.desc(), CourseDraft.id.desc())
        ).all()
    )

    project_rows = []
    project_choices = []
    for project in projects:
        nodes = list(
            session.exec(
                select(KnowledgeNode).where(KnowledgeNode.project_id == project.id)
            ).all()
        )
        mastered = sum(node.status == "mastered" for node in nodes)
        progress = f"{mastered}/{len(nodes)}" if nodes else "0/0"
        project_rows.append(
            [
                project.id,
                project.title or project.topic,
                project.topic,
                len(nodes),
                progress,
                PROJECT_STATUS_LABELS.get(project.status, project.status),
                project.updated_at.strftime("%Y-%m-%d %H:%M"),
            ]
        )
        project_choices.append((f"{project.title or project.topic} · #{project.id}", str(project.id)))

    draft_rows = []
    draft_choices = []
    for draft in drafts:
        stage, percent = DRAFT_STATUS_LABELS.get(draft.status, (draft.status, 0))
        title = _draft_title(draft)
        draft_rows.append(
            [
                draft.id,
                title,
                stage,
                f"{percent}%",
                draft.material_name or "—",
                draft.updated_at.strftime("%Y-%m-%d %H:%M"),
            ]
        )
        draft_choices.append((f"{title} · {stage} · #{draft.id}", str(draft.id)))

    return {
        "projects": projects,
        "drafts": drafts,
        "project_rows": project_rows,
        "draft_rows": draft_rows,
        "project_choices": project_choices,
        "draft_choices": draft_choices,
    }


def get_owned_draft(
    session: Session, draft_id: int, owner_id: str = "default"
) -> CourseDraft:
    draft = session.get(CourseDraft, int(draft_id))
    if draft is None or draft.owner_id != owner_id:
        raise ValueError("课程草稿不存在或无权访问")
    if draft.status in {"published", "archived"} or draft.published_project_id:
        raise ValueError("这个草稿已经结束，不能继续编辑")
    return draft


def delete_owned_draft(
    session: Session, draft_id: int, owner_id: str = "default"
) -> dict:
    draft = get_owned_draft(session, draft_id, owner_id)
    sources = list(
        session.exec(select(CourseSource).where(CourseSource.draft_id == draft.id)).all()
    )
    for source in sources:
        session.delete(source)
    session.delete(draft)
    session.commit()
    return {"draft_id": int(draft_id), "deleted_sources": len(sources)}


def delete_owned_project(
    session: Session, project_id: int, owner_id: str = "default"
) -> dict:
    project = session.get(LearningProject, int(project_id))
    if project is None or project.user_id != owner_id:
        raise ValueError("课程不存在或无权访问")
    return delete_project(session, int(project_id))
