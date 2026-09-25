"""测验页 / 复习页的事件接线与状态流转测试。

这两页在「路线 A」里被重写成一次一题 / 一次一张的流程，
这里验证的是页面函数真的把状态推对了——尤其是
「重复提交不重复计分」和「评分后自动拉下一张」。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlmodel import select

from learning_ext.db.models import Card, KnowledgeNode, ReviewLog
from learning_ext.fsrs_review import RATING_GOOD, RATING_HARD


@pytest.fixture
def quiz_page(monkeypatch, session):
    import learning_ext.pages.quiz as quiz_module

    monkeypatch.setattr(quiz_module, "engine", session.get_bind())
    return quiz_module.QuizPage(MagicMock())


@pytest.fixture
def review_page(monkeypatch, session):
    import learning_ext.pages.review as review_module

    monkeypatch.setattr(review_module, "engine", session.get_bind())
    return review_module.ReviewPage(MagicMock())


def _project_id(session, sample_project) -> str:
    return str(sample_project.id)


class TestQuizPageFlow:
    def test_output_arity_matches_registered_outputs(self, quiz_page):
        """事件注册了 10 个输出，所有分支必须返回 10 项。"""
        assert len(quiz_page._empty_result()) == 8
        assert len(quiz_page._result("x")) == 10

    def test_result_carries_status(self, quiz_page):
        result = quiz_page._result("⚠️ 出问题了")
        assert result[7]["value"] == "⚠️ 出问题了"
        assert "value" not in result[8]  # summary_md 保持原状

    def test_generate_without_project(self, quiz_page):
        result = quiz_page._generate(None, "weak", 5, "mixed")
        assert len(result) == 10
        assert "请先选择学习项目" in result[7]["value"]

    def test_generate_then_submit_then_finish(
        self, quiz_page, session, sample_project, mock_llm
    ):
        pid = _project_id(session, sample_project)
        result = quiz_page._generate(pid, "all", 1, "choice")
        assert len(result) == 10

        state = result[0]
        assert state["question_ids"]
        assert result[1]["visible"] is True  # 答题区展开
        assert result[4]["visible"] is True  # 选择题 → 单选框可见
        assert result[5]["visible"] is False  # 文本框隐藏
        assert state["request_id"]

        _, feedback, status = quiz_page._submit(state, "A", "")
        assert "答对" in feedback
        assert "下一题" in status

        finished = quiz_page._next_question(state)
        assert len(finished) == 10
        assert "共 1 题" in finished[8]["value"]

    def test_wrong_choice_is_reported(self, quiz_page, session, sample_project, mock_llm):
        pid = _project_id(session, sample_project)
        state = quiz_page._generate(pid, "all", 1, "choice")[0]
        _, feedback, _ = quiz_page._submit(state, "C", "")
        assert "答错" in feedback
        assert "概念不清" in feedback

    def test_submit_without_state(self, quiz_page):
        _, _, status = quiz_page._submit(None, None, "")
        assert "请先生成测验" in status

    def test_generate_with_empty_scope(self, quiz_page, session, sample_project):
        for node in session.exec(select(KnowledgeNode)).all():
            node.status = "mastered"
            node.mastery = 1.0
            session.add(node)
        session.commit()
        result = quiz_page._generate(_project_id(session, sample_project), "weak", 3, "short")
        assert "没有可出题的知识点" in result[7]["value"]

    def test_resubmitting_same_question_scores_once(
        self, quiz_page, session, sample_project, mock_llm
    ):
        from learning_ext.db.models import QuizAttempt

        pid = _project_id(session, sample_project)
        state = quiz_page._generate(pid, "all", 1, "choice")[0]

        quiz_page._submit(state, "A", "")
        quiz_page._submit(state, "C", "")  # 双击 / 网络重试

        assert len(session.exec(select(QuizAttempt)).all()) == 1

    def test_llm_failure_is_recoverable(self, quiz_page, session, sample_project, monkeypatch):
        import learning_ext.quiz.service as quiz_svc

        pid = _project_id(session, sample_project)
        with monkeypatch.context() as failure:
            failure.setattr(
                quiz_svc, "chat_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("超时"))
            )
            failed = quiz_page._generate(pid, "all", 1, "choice")
        assert "生成失败" in failed[7]["value"]

        # 恢复后重试应当成功
        ok = quiz_page._generate(pid, "all", 1, "choice")
        assert ok[0]["question_ids"]

    def test_retry_without_wrong_answers(self, quiz_page, session, sample_project, mock_llm):
        pid = _project_id(session, sample_project)
        state = quiz_page._generate(pid, "all", 1, "choice")[0]
        quiz_page._submit(state, "A", "")
        result = quiz_page._retry(state)
        assert "没有错题" in result[7]["value"]

    def test_retry_quiz_after_wrong_answer(self, quiz_page, session, sample_project, mock_llm):
        pid = _project_id(session, sample_project)
        state = quiz_page._generate(pid, "all", 1, "choice")[0]
        quiz_page._submit(state, "C", "")

        result = quiz_page._retry(state)
        new_state = result[0]
        assert new_state["quiz_id"] != state["quiz_id"]
        assert new_state["index"] == 0
        assert len(new_state["question_ids"]) == 1
        # 展示重测第一题时就生成了新的 request_id，与首测的那次不复用
        assert new_state["request_id"].startswith(f"quiz{new_state['quiz_id']}-")
        assert new_state["request_id"] != state["request_id"]
        assert "重测" in result[8]["value"]


class TestReviewPageFlow:
    def test_project_sentinel_maps_to_none(self, review_page):
        from learning_ext.pages.review import ALL_PROJECTS

        assert review_page._pid(ALL_PROJECTS) is None
        assert review_page._pid(None) is None
        assert review_page._pid("") is None
        assert review_page._pid("7") == 7
        assert review_page._pid("abc") is None

    def test_idle_returns_eight_updates(self, review_page):
        assert len(review_page._idle("状态")) == 8
        assert review_page._idle("状态")[7]["value"] == "状态"

    def _two_due_cards(self, session, sample_project):
        node = session.exec(
            select(KnowledgeNode).where(KnowledgeNode.project_id == sample_project.id)
        ).first()
        now = datetime.utcnow()
        cards = []
        for i, hours in enumerate([2, 1]):
            card = Card(
                user_id="default",
                node_id=node.id,
                project_id=sample_project.id,
                front=f"卡片{i}",
                back=f"答案{i}",
                next_review=now - timedelta(hours=hours),
            )
            session.add(card)
            cards.append(card)
        session.commit()
        for c in cards:
            session.refresh(c)
        return cards

    def test_load_next_shows_card_and_creates_request_id(
        self, review_page, session, sample_project
    ):
        first, _ = self._two_due_cards(session, sample_project)
        output = review_page._load_next(str(sample_project.id))
        assert len(output) == 8
        assert first.front in output[2]["value"]
        assert output[3]["value"] == first.back
        assert output[6]["open"] is False
        assert output[4] == first.id
        assert output[5].startswith(f"review{first.id}-")

    def test_load_next_when_nothing_due(self, review_page, session, sample_project):
        import learning_ext.pages.review as review_module

        output = review_page._load_next(str(sample_project.id))
        assert output[2]["value"] == review_module.DONE_FRONT
        assert output[4] is None
        assert output[5] is None

    def test_rate_without_card_loaded(self, review_page, session, sample_project):
        chunks = list(review_page._rate(None, None, RATING_GOOD, str(sample_project.id)))
        assert len(chunks) == 1
        assert "请先点击" in chunks[0][7]["value"]

    def test_rate_saves_refreshes_stats_and_advances(
        self, review_page, session, sample_project
    ):
        first, second = self._two_due_cards(session, sample_project)
        pid = str(sample_project.id)

        gen = review_page._rate(first.id, "req-1", RATING_GOOD, pid)
        pending = next(gen)
        assert len(pending) == 8
        assert "正在记录" in pending[7]["value"]  # 进行中状态先于落库

        final = list(gen)[-1]
        assert "已记录" in final[7]["value"]
        assert final[4] == second.id  # 自动拉下一张
        assert second.front in final[2]["value"]
        assert final[3]["value"] == second.back
        assert final[6]["open"] is False
        assert "总卡片数" in final[0]["value"]

        logs = session.exec(select(ReviewLog)).all()
        assert len(logs) == 1

    def test_duplicate_rating_does_not_double_count(
        self, review_page, session, sample_project
    ):
        first, _ = self._two_due_cards(session, sample_project)
        pid = str(sample_project.id)

        list(review_page._rate(first.id, "same-req", RATING_GOOD, pid))
        list(review_page._rate(first.id, "same-req", RATING_HARD, pid))

        logs = session.exec(select(ReviewLog)).all()
        assert len(logs) == 1
        assert logs[0].rating == RATING_GOOD
        session.expire_all()
        assert session.get(Card, first.id).reps == 1

    def test_all_four_ratings_share_one_handler(self, review_page, session, sample_project):
        """四个按钮必须绑定同一个生成器, 且各自带不同的 rating。"""
        first, _ = self._two_due_cards(session, sample_project)
        pid = str(sample_project.id)
        for i, rating in enumerate([1, 2, 3, 4]):
            list(review_page._rate(first.id, f"req-{i}", rating, pid))
        logs = session.exec(select(ReviewLog).order_by(ReviewLog.id)).all()
        assert [log.rating for log in logs] == [1, 2, 3, 4]

    def test_save_card_requires_selection(self, review_page):
        _, status = review_page._save_card(None, "问", "答")
        assert "请先选择一张卡片" in status

    def test_save_card_roundtrip(self, review_page, session, sample_project):
        card = self._two_due_cards(session, sample_project)[0]
        update, status = review_page._save_card(card.id, "改后的问", "改后的答")
        assert "已保存" in status
        assert update["value"] == str(card.id)
        session.expire_all()
        assert session.get(Card, card.id).front == "改后的问"

    def test_save_card_rejects_empty(self, review_page, session, sample_project):
        card = self._two_due_cards(session, sample_project)[0]
        _, status = review_page._save_card(card.id, "", "")
        assert "保存失败" in status

    def test_generate_cards_without_node(self, review_page, session, sample_project):
        _, status = review_page._generate_cards(str(sample_project.id), None, 3)
        assert "请先选择知识点" in status
