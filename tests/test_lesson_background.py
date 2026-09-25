from types import SimpleNamespace

import pytest


def test_job_deduplicates_and_allows_failed_retry(monkeypatch):
    from learning_ext import lesson_jobs as jobs

    submitted = []
    monkeypatch.setattr(jobs, "_jobs", {})
    monkeypatch.setattr(jobs, "_pool", SimpleNamespace(submit=lambda *args: submitted.append(args)))
    monkeypatch.setattr(jobs, "generate_node_summary_to_db", lambda *args, **kw: False)
    jobs.enqueue(123, "Java")
    jobs.enqueue(123, "Java", force=True)
    assert len(submitted) == 1
    fn, *args = submitted[0]
    fn(*args)
    assert jobs._jobs[123]["status"] == "failed"
    jobs.enqueue(123, "Java", force=True)
    assert len(submitted) == 2


def test_full_body_and_missing_body_do_not_wait_for_llm(monkeypatch):
    from learning_ext import lesson_jobs as jobs
    from learning_ext.pages.study_workbench import StudyWorkbenchPage

    submitted = []
    monkeypatch.setattr(jobs, "enqueue", lambda *args: submitted.append(args))
    page = object.__new__(StudyWorkbenchPage)
    body = "正文" * 12000
    assert page._truncate_guide(body) == body
    assert page._ensure_course_content(123, "Java", body) == body
    assert submitted == []
    page._ensure_course_content(123, "Java", "简介")
    assert submitted == [(123, "Java")]


def test_llm_bounds_retries_and_rejects_truncation(monkeypatch):
    from learning_ext.llm import client

    calls = []
    class Overload(Exception):
        status_code = 503

    def create(**kwargs):
        calls.append(kwargs)
        raise Overload("overloaded")

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(client, "_get_client", lambda: (fake, {"chat_model": "test"}))
    monkeypatch.setattr(client.time, "sleep", lambda _: None)
    with pytest.raises(Overload):
        client.chat("test", retries=5)
    assert len(calls) == 3
    fake.chat.completions.create = lambda **kw: SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content="incomplete"), finish_reason="length")])
    with pytest.raises(RuntimeError, match="长度上限"):
        client.chat("test")


def test_long_lesson_uses_non_thinking_deepseek_and_reports_job_error(monkeypatch):
    from learning_ext.llm import client
    from learning_ext import lesson_jobs as jobs

    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="正文"), finish_reason="stop")])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(client, "_get_client", lambda: (fake, {
        "chat_model": "deepseek-v4-flash", "base_url": "https://api.deepseek.com",
    }))
    assert client.chat("test", thinking=False, max_tokens=8192, timeout=180) == "正文"
    assert calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert calls[0]["timeout"] == 180

    monkeypatch.setattr(jobs, "_jobs", {})
    def failed(*args, **kwargs):
        raise RuntimeError("模型输出达到长度上限")
    monkeypatch.setattr(jobs, "generate_node_summary_to_db", failed)
    job = {"status": "queued", "started": None, "error": ""}
    jobs._run(42, "Java", False, job)
    monkeypatch.setattr(jobs, "_jobs", {42: job})
    assert "模型输出达到长度上限" in jobs.status(42)


def test_lesson_generation_reserves_output_for_full_body(monkeypatch):
    from learning_ext.progress import study

    captured = {}

    def fake_chat(prompt, **kwargs):
        captured.update(kwargs)
        return "完整正文"

    monkeypatch.setattr(study, "chat", fake_chat)
    node = SimpleNamespace(code="1.1", title="Java 基础", difficulty=2,
                           est_hours=1, description="变量与类型")
    assert study.generate_node_summary(node, "Java") == "完整正文"
    assert captured["max_tokens"] == 8192
    assert captured["thinking"] is False
    assert captured["timeout"] == 180
