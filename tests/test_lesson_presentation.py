from types import SimpleNamespace

from learning_ext.progress.lesson_presentation import present_lesson


def test_legacy_lesson_preserves_code_and_body():
    node = SimpleNamespace(code="1.1.4", title="异常处理", est_hours=1, difficulty=2)
    original = "## 📌 本节导览\n衔接说明\n\n---\n\n## 🎯 学习目标\n- 能解释异常\n\n## 💻 示例\n```markdown\n## 🎯 学习目标\n```\n答案保留"
    result = present_lesson(node, original)
    assert result.startswith("# 1.1.4 异常处理")
    assert "建议时长：60 分钟" in result
    assert "> 衔接说明" in result
    assert "## 一、本节目标" in result
    assert "## 二、示例" in result
    assert "---\n>" not in result
    assert "```markdown\n## 🎯 学习目标\n```" in result
    assert "- 能解释异常" in result
    assert result.endswith("答案保留")
    assert present_lesson(node, result) == result


def test_current_lesson_and_pending_text_unchanged():
    for body in ("# 1.1.3 继承\n\n> 所属单元：Java\n\n## 一、本节目标\n正文", "**正在生成**"):
        assert present_lesson(None, body) == body
