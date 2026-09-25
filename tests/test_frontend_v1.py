from pathlib import Path
from types import SimpleNamespace

import gradio as gr
import pytest


def test_course_page_builds_as_one_registered_page(session, sample_project, monkeypatch):
    import learning_ext.pages.courses as courses
    import learning_ext.pages.study_workbench as workbench
    from learning_ext.db.models import KnowledgeNode
    from learning_ext.progress.study import STATUS_MASTERED
    from sqlmodel import select

    monkeypatch.setattr(courses, "engine", session.get_bind())
    monkeypatch.setattr(workbench, "engine", session.get_bind())
    with gr.Blocks(analytics_enabled=False) as demo:
        page = courses.CoursePage(SimpleNamespace(app=demo, tabs=gr.Tabs()))
        page.on_building_ui()
        page.on_register_events()

    assert page.project_id.elem_id == "le-course-project-picker"
    assert page.base_nodes.elem_id == "le-course-stage-base"
    assert not hasattr(page, "auto_setup_btn")
    assert len(demo.fns) >= 20

    loaded = page._course_reload(str(sample_project.id))
    assert loaded[0]["value"] == str(sample_project.id)
    assert loaded[3]["choices"]
    assert loaded[10] is not None
    assert loaded[14] == loaded[15]
    assert loaded[6] == ""

    nodes = session.exec(
        select(KnowledgeNode).where(KnowledgeNode.project_id == sample_project.id)
    ).all()
    first = next(node for node in nodes if node.stage == "base")
    target = next(node for node in nodes if node.stage == "strengthen")

    saved = []
    monkeypatch.setattr(
        page,
        "_save_note",
        lambda nid, pid, content: saved.append((nid, pid, content)) or "✅ 笔记已保存",
    )
    switched = page._node_change_course(
        str(target.id),
        str(first.id),
        sample_project.id,
        "未保存的测试笔记",
        "",
    )
    assert len(switched) == 13
    assert switched[0] == target.id
    assert switched[4] == switched[5]
    assert saved == [(first.id, sample_project.id, "未保存的测试笔记")]
    assert "自动保存" in switched[-1]

    ignored = page._node_change_course(
        None,
        str(target.id),
        sample_project.id,
        "不会被覆盖",
        "旧值",
    )
    assert len(ignored) == 13
    assert all(item.get("__type__") == "update" for item in ignored)

    status = page._status_change(first.id, STATUS_MASTERED)
    assert len(status) == 8
    assert "学习进度" in status[5]
    assert status[6] == ""
    assert "已掌握" in status[7]


def test_learning_app_uses_course_entry_without_dashboard():
    source = Path("learning_ext/app.py").read_text(encoding="utf-8")

    assert '"我的课程"' in source
    assert '"🎯 学习路线"' not in source
    assert '"📚 学习工作台"' not in source
    assert '"learning_course_page"' in source
    assert '"learning_review_page"' in source
    assert '"learning_quiz_page"' in source
    assert '"learning_dashboard_page"' not in source
    assert '"learning-dashboard-tab"' not in source


def test_learning_tabs_use_their_own_vertical_scroll_container():
    source = Path("learning_ext/app.py").read_text(encoding="utf-8")

    assert "#learning-navigation > .tabitem.scrollable" in source
    assert "overflow-y: auto !important;" in source
    assert ".scrollable {max-height: none !important; overflow: visible !important;}" not in source
    assert "#learning-navigation > #learning-course-tab" in source
    assert "#learning-navigation > #learning-review-tab" in source


def test_application_brand_and_version_are_overridden_by_learning_layer(monkeypatch):
    from learning_ext import APP_NAME, __version__
    import learning_ext.app as app_module
    import learning_ext.bootstrap as bootstrap
    from theflow.settings import settings as flowsettings

    app_source = Path("learning_ext/app.py").read_text(encoding="utf-8")
    launcher_source = Path("launcher.py").read_text(encoding="utf-8")
    build_source = Path("build_exe.bat").read_text(encoding="utf-8")

    assert APP_NAME == "Keep Learning"
    assert __version__ == "2.0.0"
    assert 'flowsettings.KH_APP_NAME = APP_NAME' in app_source
    assert 'flowsettings.KH_APP_VERSION = __version__' in app_source
    assert 'title="Keep Learning"' in launcher_source
    assert '--name "KeepLearning"' in build_source
    assert '--version-file "version_info.txt"' in build_source

    observed = {}
    monkeypatch.setattr(
        app_module.KotaemonApp,
        "__init__",
        lambda self: observed.update(
            name=flowsettings.KH_APP_NAME,
            version=flowsettings.KH_APP_VERSION,
        ),
    )
    monkeypatch.setattr(bootstrap, "init_learning_ext", lambda: None)
    app_module.LearningApp()
    assert observed == {"name": "Keep Learning", "version": "2.0.0"}


def test_navigation_is_local_hamburger_and_remembers_expanded_default():
    source = Path("learning_ext/assets/navigation.js").read_text(encoding="utf-8")

    assert "M4 6h16M4 12h16M4 18h16" in source
    assert "let collapsed = false" in source
    assert "localStorage" in source
    assert "展开侧栏" in source
    assert "底部" not in source


def test_v1_theme_has_blue_gray_palette_and_fixed_management_regions():
    app_source = Path("learning_ext/app.py").read_text(encoding="utf-8")
    course_source = Path("learning_ext/pages/courses.py").read_text(encoding="utf-8")

    assert "--le-primary: #536F9D" in app_source
    assert "--le-bg: #F7F8FA" in app_source
    assert "height: 360px" in course_source
    assert "max-height: 360px" in course_source
    assert "course-context-switch" in course_source
    assert "trigger_mode=\"always_last\"" in course_source
    assert "note_snapshot" in course_source
    assert "le-stage-strip" in course_source
    assert "flex: 0 0 auto !important" in course_source
    assert "flex-wrap: nowrap !important" in course_source
    assert "继续学习" not in course_source
    assert "continue_btn" not in course_source

@pytest.mark.parametrize("failure", [False, True])
def test_course_action_guard_saves_or_blocks(session, sample_project, monkeypatch, failure):
    import learning_ext.pages.courses as courses
    from learning_ext.db.models import KnowledgeNode
    from sqlmodel import select

    monkeypatch.setattr(courses, "engine", session.get_bind())
    page = courses.CoursePage(SimpleNamespace())
    node = session.exec(select(KnowledgeNode)).first()
    saved = []
    def save(nid, pid, text):
        saved.append((nid, pid, text))
        return "失败" if failure else "✅ 已保存"
    monkeypatch.setattr(page, "_save_note", save)
    if failure:
        with pytest.raises(gr.Error):
            page._prepare_course_action(node.id, sample_project.id, "草稿", "旧笔记")
    else:
        snapshot, notice = page._prepare_course_action(node.id, sample_project.id, "草稿", "旧笔记")
        assert snapshot == "草稿" and "自动保存" in notice
    assert saved == [(node.id, sample_project.id, "草稿")]


def test_failed_switch_restores_picker_without_overwriting_note(monkeypatch):
    from learning_ext.pages.courses import CoursePage
    page = CoursePage(SimpleNamespace())
    monkeypatch.setattr(page, "_save_changed_note", lambda *args: (False, "保存失败"))
    def unexpected(*args):
        raise AssertionError("保存失败不应重载")
    monkeypatch.setattr(page, "_course_reload", unexpected)
    result = page._course_change("2", 10, 1, "草稿", "旧笔记")
    assert len(result) == 20
    assert result[0]["value"] == "1"
    assert all(value == gr.update() for value in result[1:19])
    assert result[-1] == "保存失败"


def test_course_page_does_not_register_legacy_creation_or_environment_actions(session, sample_project, monkeypatch):
    import learning_ext.pages.courses as courses
    monkeypatch.setattr(courses, "engine", session.get_bind())
    with gr.Blocks(analytics_enabled=False) as demo:
        page = courses.CoursePage(SimpleNamespace(app=demo, tabs=gr.Tabs()))
        page.on_building_ui()
        page.on_register_events()
    handlers = {fn.fn for fn in demo.fns.values() if fn.fn}
    assert page._plan_install not in handlers
    assert page._execute_install_plan not in handlers
    assert page._apply_env not in handlers
    assert page._handle_save_with_setup not in handlers
    switch = next(f for f in demo.fns.values() if f.fn == page._course_change)
    assert switch.outputs[0] is page.project_id


def test_failed_home_save_does_not_reload_current_course(monkeypatch):
    from learning_ext.pages.courses import CoursePage
    page = CoursePage(SimpleNamespace())
    def unexpected(*args):
        raise AssertionError('未保存成功不得切换课程')
    monkeypatch.setattr(page, '_course_reload', unexpected)
    assert page._load_created_course(None) == [gr.update() for _ in range(19)]


def test_successful_home_save_loads_new_project(monkeypatch):
    from learning_ext.pages.courses import CoursePage
    page = CoursePage(SimpleNamespace())
    loaded = []
    monkeypatch.setattr(page, '_course_reload', lambda pid: loaded.append(pid) or ['new'])
    assert page._load_created_course(42) == ['new']
    assert loaded == [42]
