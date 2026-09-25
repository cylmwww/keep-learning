"""真实 LLM 集成测试 - 用真实 API 验证业务链路 (需配置好 .env)。

跑这个测试前确保 kotaemon/.env 配好了有效的 API Key。
默认 skip, 设环境变量 RUN_LLM_TESTS=1 启用。
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_LLM_TESTS"),
    reason="设 RUN_LLM_TESTS=1 启用真实 LLM 测试 (消耗 API 配额)",
)


@pytest.fixture(scope="module")
def llm_ready():
    """确认 LLM 配置可用。"""
    from learning_ext.llm import chat

    try:
        r = chat("只回复两个字:你好", max_tokens=20)
        assert r and len(r) > 0
        return True
    except Exception as e:
        pytest.skip(f"LLM 不可用, 跳过: {e}")


class TestRealLLM:
    def test_chat_returns_meaningful(self, llm_ready):
        from learning_ext.llm import chat

        r = chat("1+1等于几? 只回复数字", max_tokens=10)
        assert "2" in r

    def test_chat_json_returns_valid(self, llm_ready):
        from learning_ext.llm import chat_json

        r = chat_json('返回JSON: {"answer": 42}。只返回这个JSON。')
        assert r.get("answer") == 42

    def test_generate_roadmap_real(self, llm_ready):
        """真实生成路线, 验证结构完整。"""
        from learning_ext.path_generator import generate_roadmap

        roadmap = generate_roadmap("学Git基础", "新手", "会用Git管理代码", 5)
        assert "nodes" in roadmap
        assert len(roadmap["nodes"]) >= 5  # 真实应生成 10+
        # 每个节点必备字段
        for n in roadmap["nodes"]:
            assert "code" in n
            assert "title" in n
            assert "stage" in n
        # 至少有依赖关系
        has_dep = any(n.get("prerequisites") for n in roadmap["nodes"])
        assert has_dep

    def test_generate_node_summary_real(self, llm_ready, session):
        """真实生成教学内容 (不依赖 mock_llm, 独立建数据)。"""
        from sqlmodel import select
        from learning_ext.db.models import KnowledgeNode, LearningProject
        from learning_ext.progress.study import generate_node_summary

        # 独立建项目+节点 (不用 sample_project fixture, 避免触发 mock_llm)
        p = LearningProject(
            user_id="default",
            topic="学Git",
            background="",
            goal="",
            weekly_hours=5,
            roadmap_json="{}",
            status="active",
        )
        session.add(p)
        session.commit()
        n = KnowledgeNode(
            project_id=p.id,
            code="1.1",
            title="Git基础概念",
            description="",
            stage="base",
            est_hours=2,
            difficulty=2,
        )
        session.add(n)
        session.commit()

        summary = generate_node_summary(n, p.topic)
        assert isinstance(summary, str)
        assert len(summary) > 100  # 有实质内容
        # 应包含某些关键章节词
        assert any(kw in summary for kw in ["概念", "要点", "学习", "掌握"])

    def test_env_checklist_real(self, llm_ready):
        """真实生成环境清单。"""
        from learning_ext.progress.study import generate_env_checklist

        md = generate_env_checklist("学Rust", "有编程基础")
        assert len(md) > 50

    def test_generate_cards_real(self, llm_ready, session):
        """真实生成复习卡片 (不依赖 mock_llm)。"""
        from sqlmodel import select
        from learning_ext.db.models import KnowledgeNode, LearningProject
        from learning_ext.fsrs_review import generate_cards_from_node

        p = LearningProject(
            user_id="default",
            topic="学Python",
            background="",
            goal="",
            weekly_hours=5,
            roadmap_json="{}",
            status="active",
        )
        session.add(p)
        session.commit()
        n = KnowledgeNode(
            project_id=p.id,
            code="1.1",
            title="Python变量",
            description="",
            stage="base",
            est_hours=1,
            difficulty=1,
        )
        session.add(n)
        session.commit()

        cards = generate_cards_from_node(
            session,
            n.id,
            "default",
            "Python 是一门解释型编程语言, 变量用来存储数据",
            count=3,
        )
        assert len(cards) >= 1
        for c in cards:
            assert c.front
            assert c.back
