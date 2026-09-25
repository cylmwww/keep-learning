import json
from types import SimpleNamespace

import gradio as gr
import pytest
from sqlmodel import select


def _research_payload():
    return {
        "summary": "以教材主线为准，补充一项实践资料。",
        "topic": "测试课程",
        "core_areas": ["基础", "实践"],
        "prerequisites": ["无"],
        "suggested_extensions": [],
        "questions": [
            {
                "id": f"q{i}",
                "title": f"问题{i}",
                "reason": "调整课程",
                "type": "single",
                "options": [
                    {"value": "a", "label": "选项A", "description": "初级"},
                    {"value": "b", "label": "选项B", "description": "进阶"},
                ],
            }
            for i in range(1, 5)
        ],
    }


def _blueprint_payload():
    lessons = []
    for i in range(1, 6):
        lessons.append(
            {
                "code": f"1.1.{i}",
                "title": f"课节{i}",
                "objective": f"完成目标{i}",
                "minutes": 45,
                "difficulty": 2,
                "depth": ["直观理解", "应用实践"],
                "prerequisites": [f"1.1.{i - 1}"] if i > 1 else [],
            }
        )
    return {
        "title": "测试课程",
        "summary": "为测试学习者设计。",
        "units": [{"title": "基础单元", "lectures": [{"title": "第一讲", "lessons": lessons}]}],
    }


def test_v2_draft_preview_publish_and_idempotency(session, monkeypatch):
    import learning_ext.course_creation.service as service
    from learning_ext.db.models import (
        CourseDraft,
        KnowledgeNode,
        LessonContentRevision,
        LearningProject,
    )

    responses = iter([
        {"queries": ["测试课程 教材", "测试课程 官方资料"]},
        _research_payload(),
        _blueprint_payload(),
    ])
    monkeypatch.setattr(service, "chat_json", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(
        service,
        "_search_web",
        lambda query: [{"title": "真实测试资料", "url": "https://example.com/doc", "excerpt": query}],
    )
    monkeypatch.setattr(
        service,
        "chat",
        lambda *args, **kwargs: "## 本节目标\n" + "完整课程内容。" * 80 + "\n## 练习与参考答案\n答案。",
    )

    draft = service.create_draft(session, "user-a", "学习测试课程")
    research = service.run_research(session, draft.id, "user-a")
    assert len(research["questions"]) == 4
    assert research["sources"][0]["url"] == "https://example.com/doc"

    answers = {f"q{i}": ["a"] for i in range(1, 5)}
    blueprint = service.build_blueprint(session, draft.id, answers, "user-a")
    assert len(service.get_ordered_lessons(blueprint)) == 5

    preview = service.generate_preview(session, draft.id, "user-a")
    assert [item["code"] for item in preview] == ["1.1.1", "1.1.2", "1.1.3"]

    project_id = service.publish_course(session, draft.id, "user-a")
    assert service.publish_course(session, draft.id, "user-a") == project_id
    project = session.get(LearningProject, project_id)
    assert project.user_id == "user-a"
    assert json.loads(project.course_blueprint_json)["title"] == "测试课程"
    assert "问题1" in project.background

    nodes = session.exec(
        select(KnowledgeNode).where(KnowledgeNode.project_id == project_id)
    ).all()
    assert len(nodes) == 5
    generated = [node for node in nodes if node.description.startswith("## 本节目标")]
    assert len(generated) == 3
    revisions = session.exec(
        select(LessonContentRevision).where(
            LessonContentRevision.project_id == project_id
        )
    ).all()
    assert len(revisions) == 3
    assert session.get(CourseDraft, draft.id).status == "published"


def test_v2_owner_boundary_and_blueprint_validation(session):
    import learning_ext.course_creation.service as service

    draft = service.create_draft(session, "user-a", "学习测试课程")
    with pytest.raises(ValueError, match="无权访问"):
        service.run_research(session, draft.id, "user-b")

    invalid = _blueprint_payload()
    invalid["units"][0]["lectures"][0]["lessons"][0]["prerequisites"] = ["9.9.9"]
    with pytest.raises(ValueError, match="前置课节"):
        service._validate_blueprint(invalid)


def test_v2_publish_requires_current_complete_preview(session):
    import learning_ext.course_creation.service as service

    draft = service.create_draft(session, "default", "学习测试课程")
    draft.blueprint_json = json.dumps(_blueprint_payload(), ensure_ascii=False)
    draft.answers_json = "{}"
    draft.status = "awaiting_course_confirmation"
    session.add(draft)
    session.commit()

    with pytest.raises(ValueError, match="预览"):
        service.publish_course(session, draft.id)


def test_v2_creator_page_registers_four_step_flow(session, monkeypatch):
    import learning_ext.pages.course_creator as page_module

    monkeypatch.setattr(page_module, "engine", session.get_bind())
    with gr.Blocks(analytics_enabled=False) as demo:
        tabs = gr.Tabs()
        page = page_module.CourseCreatorPage(SimpleNamespace(app=demo, tabs=tabs))
        page.on_building_ui()
        page.on_register_events()

    assert page.topic_input.label == "你想学习什么？"
    assert len(page.question_inputs) == 6
    assert page.blueprint_modal.elem_id == "le-blueprint-modal"
    handlers = [fn.fn for fn in demo.fns.values() if fn.fn]
    assert page._start_creation in handlers
    assert page._build_blueprint in handlers
    assert page._generate_preview in handlers
    assert page._publish in handlers


def test_v2_creator_keeps_draft_id_before_committed_instance_detaches(
    session, monkeypatch
):
    import learning_ext.pages.course_creator as page_module
    from learning_ext.db.models import CourseDraft
    from learning_ext.pages.course_creator import CourseCreatorPage

    def committed_research(db_session, draft_id, owner_id):
        draft = db_session.get(CourseDraft, draft_id)
        draft.status = "awaiting_answers"
        db_session.add(draft)
        db_session.commit()
        return {
            "topic": "Java Agent",
            "summary": "调研完成。",
            "queries": [],
            "sources": [],
            "suggested_extensions": [],
            "questions": [],
        }

    monkeypatch.setattr(page_module, "engine", session.get_bind())
    monkeypatch.setattr(page_module, "run_research", committed_research)
    page = CourseCreatorPage(SimpleNamespace())

    result = page._start_creation("学习 Java Agent", None)

    assert isinstance(result[0], int)
    assert session.get(CourseDraft, result[0]).status == "awaiting_answers"
