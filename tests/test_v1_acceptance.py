import asyncio
import inspect
from types import SimpleNamespace

import gradio as gr
import pytest
from sqlmodel import select

from learning_ext.db.models import Card, KnowledgeNode, ReviewLog
from learning_ext.llm import LLMOutputError
from learning_ext.practice import auto_setup as auto
from learning_ext.quiz.service import _parse_question


@pytest.mark.parametrize("rating", [1, 2, 3, 4])
def test_registered_review_event_executes_in_gradio(session, sample_project, monkeypatch, rating):
    import learning_ext.pages.review as module

    monkeypatch.setattr(module, "engine", session.get_bind())
    node = session.exec(select(KnowledgeNode)).first()
    card = Card(node_id=node.id, project_id=sample_project.id, user_id="default",
                front="问题", back="答案")
    session.add(card)
    session.commit()
    session.refresh(card)
    with gr.Blocks(analytics_enabled=False) as demo:
        page = module.ReviewPage(SimpleNamespace(app=demo))
        page.on_building_ui()
        page.on_register_events()
    callbacks = [f for f in demo.fns.values() if getattr(f.fn, "__name__", "") == "handle"]
    assert len(callbacks) == 4
    callback = callbacks[rating - 1]
    assert inspect.isgeneratorfunction(callback.fn)
    assert callback.concurrency_id == "review"
    loaded = page._load_next(str(sample_project.id))
    assert loaded[3]["value"] == "答案"
    assert loaded[6]["open"] is False

    async def run():
        result = await demo.call_function(callback, [card.id, "display-1", str(sample_project.id)])
        demo.validate_outputs(callback, result["prediction"])
        assert all(not item["interactive"] for item in result["prediction"][8:])
        result = await demo.call_function(callback, [], iterator=result["iterator"])
        demo.validate_outputs(callback, result["prediction"])
        result = await demo.call_function(callback, [], iterator=result["iterator"])
        assert all(item["interactive"] == bool(result["prediction"][4]) for item in result["prediction"][8:12])
        assert result["prediction"][12]["interactive"]
        result["iterator"].iterator.close()
        return result

    result = asyncio.run(run())
    assert "已记录" in result["prediction"][7]["value"]
    session.expire_all()
    logs = session.exec(select(ReviewLog)).all()
    assert len(logs) == 1 and logs[0].rating == rating


def test_old_card_cannot_be_rated_in_different_project(session, sample_project, monkeypatch):
    import learning_ext.pages.review as module
    monkeypatch.setattr(module, "engine", session.get_bind())
    node = session.exec(select(KnowledgeNode)).first()
    card = Card(node_id=node.id, project_id=sample_project.id, user_id="default", front="问题", back="答案")
    session.add(card)
    session.commit()
    page = module.ReviewPage(SimpleNamespace())
    result = list(page._rate(card.id, "old-display", 3, str(sample_project.id + 999)))[-1]
    assert result[4] is None
    assert session.exec(select(ReviewLog)).all() == []


def test_install_plan_is_bound_to_project(monkeypatch):
    from learning_ext.pages.study_workbench import StudyWorkbenchPage
    plan = auto.build_install_plan([{"cmd": "winget install --id Git.Git -e"}], source_digest="1")
    def fail(*args, **kw):
        raise AssertionError("不应执行旧项目计划")
    monkeypatch.setattr(auto, "execute_plan", fail)
    page = StudyWorkbenchPage(SimpleNamespace())
    result = list(page._execute_install_plan(auto.plan_to_state(plan), True, "2"))
    assert "项目已切换" in result[0][1]


@pytest.mark.parametrize("command", [
    "Test-Path (New-Item -ItemType Directory probe)",
    "Get-Command { New-Item -ItemType Directory probe }",
    "Test-Path $env:USERPROFILE",
])
def test_readonly_checks_reject_expressions(command):
    assert auto.screen_command(command, readonly=True)


@pytest.mark.parametrize("output,timeout,installs", [("False", False, True), ("True", False, False), ("", True, False)])
def test_path_check_uses_boolean_result(monkeypatch, tmp_path, output, timeout, installs):
    calls = []
    def run(cmd, **kwargs):
        calls.append(cmd)
        yield output
        yield ("__exit__", 0, timeout if cmd.startswith("Test-Path") else False)
    monkeypatch.setattr(auto, "_run_command", run)
    plan = auto.build_install_plan([{
        "cmd": "New-Item -ItemType Directory -Path example",
        "check": "Test-Path example",
    }])
    list(auto.execute_plan(plan, plan.digest, workdir=str(tmp_path)))
    assert (len(calls) == 2) is installs


@pytest.mark.parametrize("code", [None, "unknown"])
def test_multinode_question_cannot_guess_knowledge_node(code):
    question = {"qtype": "short", "stem": "问题", "answer": "答案", "node_code": code}
    with pytest.raises(LLMOutputError):
        _parse_question(question, 0, {"A": 1, "B": 2})


def test_local_pip_executes_project_python_without_shell(tmp_path, monkeypatch):
    import io
    python = tmp_path / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    captured = []
    class Process:
        stdout = io.StringIO("")
        returncode = 0
        def wait(self, **kw):
            return 0
    def popen(args, **kw):
        captured.append(args)
        return Process()
    monkeypatch.setattr(auto.subprocess, "Popen", popen)
    cmd = r".venv\Scripts\pip.exe install requests==2.32.3"
    assert auto.screen_command(cmd, readonly=False) is None
    list(auto._run_command(cmd, cwd=str(tmp_path), timeout=3, env={}))
    assert captured == [[str(python.resolve()), "-m", "pip", "install", "requests==2.32.3"]]


def test_modified_plan_object_cannot_reuse_confirmation(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("不能启动进程")
    monkeypatch.setattr(auto.subprocess, "Popen", fail)
    plan = auto.build_install_plan([{"cmd": "winget install --id Python.Python.3.12 -e"}])
    digest = plan.digest
    plan.steps[0].cmd = "winget install --id Git.Git -e"
    assert "摘要与确认时不符" in "".join(auto.execute_plan(plan, digest, workdir=str(tmp_path)))


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows 进程树")
def test_timeout_kills_spawned_child(tmp_path):
    import subprocess
    import sys
    script = tmp_path / "process_tree.py"
    script.write_text(
        "import subprocess,sys,time\n"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\n"
        "print('CHILD:'+str(child.pid),flush=True)\n"
        "time.sleep(60)\n", encoding="utf-8",
    )
    command = "& '" + sys.executable.replace("'", "''") + "' '" + str(script).replace("'", "''") + "'"
    chunks = list(auto._run_command(command, cwd=str(tmp_path), timeout=3, env=auto.minimal_env()))
    child_pid = int(next(c.strip().split(":")[1] for c in chunks if isinstance(c, str) and c.startswith("CHILD:")))
    try:
        assert chunks[-1][2] is True
        check = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", f"Get-Process -Id {child_pid} -ErrorAction SilentlyContinue"],
            capture_output=True, text=True, timeout=10,
        )
        assert not check.stdout.strip(), "超时后子进程仍在运行"
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(child_pid)], capture_output=True, timeout=10)
