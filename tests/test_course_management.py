import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import gradio as gr
import pytest
from sqlmodel import select


def test_course_management_lists_only_owned_projects_and_active_drafts(session):
    from learning_ext.course_management import course_management_snapshot
    from learning_ext.db.models import CourseDraft, KnowledgeNode, LearningProject

    project = LearningProject(
        user_id="default", title="Java 后端", topic="学习 Java", status="active"
    )
    other_project = LearningProject(
        user_id="other", title="别人的课程", topic="不可见", status="active"
    )
    session.add(project)
    session.add(other_project)
    session.commit()
    session.refresh(project)
    session.add(
        KnowledgeNode(
            project_id=project.id,
            code="1.1",
            title="Java 基础",
            description="",
            stage="base",
            status="mastered",
        )
    )
    session.add(
        CourseDraft(
            owner_id="default",
            input_text="学习 Spring Boot",
            status="awaiting_answers",
        )
    )
    session.add(CourseDraft(owner_id="other", input_text="不可见草稿"))
    session.add(
        CourseDraft(owner_id="default", input_text="已归档", status="archived")
    )
    session.commit()

    snapshot = course_management_snapshot(session)

    assert [row[1] for row in snapshot["project_rows"]] == ["Java 后端"]
    assert snapshot["project_rows"][0][4] == "1/1"
    assert [row[1] for row in snapshot["draft_rows"]] == ["学习 Spring Boot"]
    assert snapshot["draft_rows"][0][2] == "填写学习问卷"


def test_delete_owned_draft_removes_sources_and_enforces_owner(session):
    from learning_ext.course_management import delete_owned_draft
    from learning_ext.db.models import CourseDraft, CourseSource

    draft = CourseDraft(owner_id="default", input_text="未完成课程")
    session.add(draft)
    session.commit()
    session.refresh(draft)
    source = CourseSource(
        draft_id=draft.id,
        owner_id="default",
        source_type="material",
        title="教材",
    )
    session.add(source)
    session.commit()

    with pytest.raises(ValueError, match="无权访问"):
        delete_owned_draft(session, draft.id, "other")

    result = delete_owned_draft(session, draft.id)

    assert result["deleted_sources"] == 1
    assert session.get(CourseDraft, draft.id) is None
    assert session.exec(
        select(CourseSource).where(CourseSource.draft_id == draft.id)
    ).first() is None


def test_delete_owned_project_reuses_course_cascade(session, sample_project):
    from learning_ext.course_management import delete_owned_project
    from learning_ext.db.models import LearningProject

    with pytest.raises(ValueError, match="无权访问"):
        delete_owned_project(session, sample_project.id, "other")

    result = delete_owned_project(session, sample_project.id)

    assert result["deleted"]["projects"] == 1
    assert session.get(LearningProject, sample_project.id) is None


def test_course_creator_restores_questionnaire_draft(session, monkeypatch):
    import learning_ext.pages.course_creator as creator_module
    from learning_ext.db.models import CourseDraft

    research = {
        "topic": "Java Agent",
        "summary": "围绕 Java Agent 构建课程。",
        "questions": [
            {
                "id": "foundation",
                "title": "你的 Java 基础如何？",
                "reason": "决定起点",
                "type": "single",
                "options": [
                    {"value": "basic", "label": "入门", "description": "刚开始"},
                    {"value": "advanced", "label": "进阶", "description": "有项目经验"},
                ],
            }
        ],
    }
    draft = CourseDraft(
        owner_id="default",
        input_text="学习 Java Agent",
        material_name="agent.pdf",
        status="awaiting_answers",
        research_json=json.dumps(research, ensure_ascii=False),
        questionnaire_json=json.dumps({"questions": research["questions"]}, ensure_ascii=False),
        answers_json=json.dumps({"foundation": ["advanced"]}, ensure_ascii=False),
    )
    session.add(draft)
    session.commit()
    session.refresh(draft)

    monkeypatch.setattr(creator_module, "engine", session.get_bind())
    with gr.Blocks(analytics_enabled=False) as demo:
        tabs = gr.Tabs()
        page = creator_module.CourseCreatorPage(SimpleNamespace(app=demo, tabs=tabs))
        page.on_building_ui()

    restored = page._resume_draft(draft.id)

    assert len(restored) == len(page.resume_outputs())
    assert restored[0] == draft.id
    assert restored[1] == "学习 Java Agent"
    assert restored[5]["value"] == ["advanced"]
    assert "agent.pdf" in restored[13]


def test_course_management_page_registers_navigation_and_actions(session, monkeypatch):
    import learning_ext.pages.course_creator as creator_module
    import learning_ext.pages.course_management as management_module
    import learning_ext.pages.courses as courses_module
    import learning_ext.pages.study_workbench as workbench_module

    monkeypatch.setattr(creator_module, "engine", session.get_bind())
    monkeypatch.setattr(management_module, "engine", session.get_bind())
    monkeypatch.setattr(courses_module, "engine", session.get_bind())
    monkeypatch.setattr(workbench_module, "engine", session.get_bind())
    with gr.Blocks(analytics_enabled=False) as demo:
        tabs = gr.Tabs()
        app = SimpleNamespace(app=demo, tabs=tabs, _tabs={})
        app.learning_creator_page = creator_module.CourseCreatorPage(app)
        app.learning_creator_page.on_building_ui()
        app.learning_course_page = courses_module.CoursePage(app)
        app.learning_course_page.on_building_ui()
        page = management_module.CourseManagementPage(app)
        page.on_building_ui()
        page.on_register_events()

    handlers = [fn.fn for fn in demo.fns.values() if fn.fn]
    assert page._delete_project in handlers
    assert page._delete_draft in handlers
    assert page._continue_draft in handlers
    assert page._open_course in handlers
    assert page._select_project_row in handlers
    assert page._select_draft_row in handlers


def test_course_management_table_rows_select_project_and_draft():
    from learning_ext.pages.course_management import CourseManagementPage

    event = SimpleNamespace(index=(1, 2))
    project_update, project_status = CourseManagementPage._select_project_row(
        [[2, "第二门课程"], [1, "第一门课程"]], event
    )
    draft_update, draft_status = CourseManagementPage._select_draft_row(
        [[4, "第二份草稿"], [3, "第一份草稿"]], event
    )

    assert project_update["value"] == "1"
    assert "第一门课程" in project_status
    assert draft_update["value"] == "3"
    assert "第一份草稿" in draft_status


def test_course_management_opens_the_selected_course():
    from learning_ext.pages.course_management import CourseManagementPage

    course = SimpleNamespace(_course_change=MagicMock(return_value=list(range(20))))
    page = CourseManagementPage(SimpleNamespace(learning_course_page=course))

    result = page._open_course("7", 11, 3, "笔记", "旧笔记")

    course._course_change.assert_called_once_with("7", 11, 3, "笔记", "旧笔记")
    assert result[:-1] == tuple(range(20))
    assert result[-1]["selected"] == "learning-course-tab"


def test_learning_app_registers_course_management_tab():
    from pathlib import Path

    source = Path("learning_ext/app.py").read_text(encoding="utf-8")
    assert '"课程管理"' in source
    assert '"learning-management-tab"' in source
    assert '"learning_management_page"' in source
