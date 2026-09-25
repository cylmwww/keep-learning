"""复习流程的可用性验收测试。

对应「路线 A」的验收点：
    - 四种评分走同一条流程，各自落一条日志
    - 同一次「展示 → 评分」重复提交只算一次，调度不被重复推进
    - 卡片能生成 / 列出 / 编辑（不再只有生成函数）
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from learning_ext.db.models import Card, KnowledgeNode, ReviewLog
from learning_ext.fsrs_review import (
    RATING_AGAIN,
    RATING_EASY,
    RATING_GOOD,
    RATING_HARD,
    generate_cards_from_node,
    get_due_cards,
    get_review_stats,
    list_cards,
    review_card,
    update_card,
)

ALL_RATINGS = [RATING_AGAIN, RATING_HARD, RATING_GOOD, RATING_EASY]


@pytest.fixture
def node(session, sample_project):
    return session.exec(
        select(KnowledgeNode).where(KnowledgeNode.project_id == sample_project.id)
    ).first()


def _card(session, node, front="问题", **kw) -> Card:
    card = Card(
        user_id="default",
        node_id=node.id,
        project_id=node.project_id,
        front=front,
        back="答案",
        **kw,
    )
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


def _logs(session, card_id: int) -> list[ReviewLog]:
    return list(
        session.exec(
            select(ReviewLog).where(ReviewLog.card_id == card_id).order_by(ReviewLog.id)
        ).all()
    )


class TestFourRatings:
    """四个评分按钮接的是同一个生成器，行为必须一致。"""

    @pytest.mark.parametrize("rating", ALL_RATINGS)
    def test_each_rating_saves_once_and_advances(self, session, node, rating):
        card = _card(session, node)
        reviewed = review_card(
            session, card.id, rating, "default", request_id=f"req-{rating}"
        )
        assert reviewed.reps == 1
        assert reviewed.stability > 0
        assert reviewed.next_review is not None
        logs = _logs(session, card.id)
        assert len(logs) == 1
        assert logs[0].rating == rating

    def test_all_four_ratings_in_sequence(self, session, node):
        card = _card(session, node)
        for i, rating in enumerate(ALL_RATINGS):
            review_card(session, card.id, rating, "default", request_id=f"req-{i}")
        reviewed = session.get(Card, card.id)
        assert reviewed.reps == 4
        assert [log.rating for log in _logs(session, card.id)] == ALL_RATINGS

    @pytest.mark.parametrize("rating", [0, 5, -1, None])
    def test_invalid_rating_rejected(self, session, node, rating):
        card = _card(session, node)
        with pytest.raises(ValueError, match="rating"):
            review_card(session, card.id, rating, "default")


class TestRequestIdDedup:
    def test_double_submit_saves_one_log(self, session, node):
        card = _card(session, node)
        review_card(session, card.id, RATING_GOOD, "default", request_id="dup")
        review_card(session, card.id, RATING_GOOD, "default", request_id="dup")
        assert len(_logs(session, card.id)) == 1

    def test_double_submit_does_not_advance_reps(self, session, node):
        card = _card(session, node)
        first = review_card(session, card.id, RATING_GOOD, "default", request_id="dup")
        reps_after_first = first.reps
        due_after_first = first.next_review

        second = review_card(session, card.id, RATING_AGAIN, "default", request_id="dup")

        assert second.reps == reps_after_first
        assert second.next_review == due_after_first  # 第二次评分完全没生效

    def test_different_request_ids_both_count(self, session, node):
        card = _card(session, node)
        review_card(session, card.id, RATING_GOOD, "default", request_id="a")
        review_card(session, card.id, RATING_GOOD, "default", request_id="b")
        assert len(_logs(session, card.id)) == 2

    def test_request_id_reused_for_another_card_raises(self, session, node):
        c1 = _card(session, node, front="Q1")
        c2 = _card(session, node, front="Q2")
        review_card(session, c1.id, RATING_GOOD, "default", request_id="shared")
        with pytest.raises(ValueError, match="占用"):
            review_card(session, c2.id, RATING_GOOD, "default", request_id="shared")

    def test_failed_scheduling_leaves_no_log(self, session, node, monkeypatch):
        """调度失败时不能留下半条记录，重新评分应正常。"""
        import learning_ext.fsrs_review.service as svc

        calls = {"n": 0}
        real = svc._get_scheduler

        class _Flaky:
            def review_card(self, *a, **k):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("调度炸了")
                return real().review_card(*a, **k)

        monkeypatch.setattr(svc, "_get_scheduler", lambda: _Flaky())
        card = _card(session, node)
        with pytest.raises(RuntimeError):
            review_card(session, card.id, RATING_GOOD, "default", request_id="r")
        assert _logs(session, card.id) == []

        reviewed = review_card(session, card.id, RATING_GOOD, "default", request_id="r")
        assert reviewed.reps == 1
        assert len(_logs(session, card.id)) == 1


class TestEmptyQueue:
    def test_no_due_cards_returns_empty(self, session, sample_project):
        assert get_due_cards(session, "default", project_id=sample_project.id) == []

    def test_all_future_cards_yield_zero_due(self, session, node):
        _card(session, node, next_review=datetime.utcnow() + timedelta(days=3))
        stats = get_review_stats(session, "default")
        assert stats["total_cards"] == 1
        assert stats["due_count"] == 0

    def test_reviewed_card_leaves_the_due_queue(self, session, node):
        card = _card(session, node, next_review=datetime.utcnow() - timedelta(hours=1))
        assert any(c.id == card.id for c in get_due_cards(session, "default"))
        review_card(session, card.id, RATING_EASY, "default")
        assert not any(c.id == card.id for c in get_due_cards(session, "default"))


class TestCardTools:
    def test_update_card_edits_wording(self, session, node):
        card = _card(session, node)
        updated = update_card(session, card.id, "  新问题  ", "  新答案  ", "default")
        assert updated.front == "新问题"
        assert updated.back == "新答案"
        assert session.get(Card, card.id).front == "新问题"

    @pytest.mark.parametrize(("front", "back"), [("", "答"), ("问", ""), ("  ", "  ")])
    def test_update_card_rejects_empty_sides(self, session, node, front, back):
        card = _card(session, node)
        with pytest.raises(ValueError, match="不能为空"):
            update_card(session, card.id, front, back, "default")

    def test_update_card_checks_owner(self, session, node):
        card = _card(session, node)
        with pytest.raises(ValueError, match="不属于"):
            update_card(session, card.id, "问", "答", "someone-else")

    def test_update_nonexistent_card_raises(self, session):
        with pytest.raises(ValueError, match="不存在"):
            update_card(session, 99999, "问", "答")

    def test_list_cards_filters_by_project_and_node(self, session, node, sample_project):
        mine = _card(session, node, front="本项目的卡")
        other_project = _card(session, node, front="别的卡")
        other_project.project_id = 99999
        session.add(other_project)
        session.commit()

        all_cards = list_cards(session, "default")
        assert {c.id for c in all_cards} >= {mine.id, other_project.id}

        by_project = list_cards(session, "default", project_id=sample_project.id)
        assert {c.id for c in by_project} == {mine.id}

        by_node = list_cards(session, "default", node_id=node.id)
        assert {c.id for c in by_node} >= {mine.id}

        assert list_cards(session, "someone-else") == []

    def test_generated_cards_are_listable_and_editable(
        self, session, node, sample_project, mock_llm
    ):
        """生成 → 列出 → 编辑 这条链在 service 层是通的。"""
        cards = generate_cards_from_node(session, node.id, "default", "内容", count=5)
        assert cards
        listed = list_cards(session, "default", node_id=node.id)
        assert {c.id for c in listed} >= {c.id for c in cards}
        edited = update_card(session, cards[0].id, "改后的问题", "改后的答案")
        assert edited.front == "改后的问题"

    def test_malformed_generated_cards_are_dropped(
        self, session, node, sample_project, monkeypatch
    ):
        import learning_ext.llm as llm_pkg

        monkeypatch.setattr(
            llm_pkg,
            "chat_json",
            lambda *a, **k: {
                "cards": [
                    "不是对象",
                    {"front": "缺 back"},
                    {"front": "好问题", "back": "好答案", "card_type": "basic"},
                ]
            },
        )
        cards = generate_cards_from_node(session, node.id, "default", "内容")
        assert [c.front for c in cards] == ["好问题"]
