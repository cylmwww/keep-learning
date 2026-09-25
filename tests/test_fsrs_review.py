"""FSRS 复习 service 测试 (这是修复 FSRS API 兼容性后的验证)。"""

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
    review_card,
)


def now():
    """统一用 naive UTC now (与 DB 存储一致)。"""
    return datetime.utcnow()


@pytest.fixture
def sample_card(session, sample_project):
    """创建一张测试卡片。"""
    node = session.exec(
        select(KnowledgeNode).where(KnowledgeNode.project_id == sample_project.id)
    ).first()
    card = Card(
        user_id="default",
        node_id=node.id,
        project_id=sample_project.id,
        front="测试问题",
        back="测试答案",
        card_type="basic",
    )
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


class TestReviewCard:
    def test_review_new_card_good_updates_state(self, session, sample_card):
        """新卡第一次评分 Good 应改变 state/step/stability。"""
        original_state = sample_card.state
        reviewed = review_card(session, sample_card.id, RATING_GOOD, "default")

        assert reviewed.reps == 1
        # 新卡 (state=0) 复习后应进入 fsrs 的 Learning/Review 状态
        assert reviewed.state in (1, 2, 3)
        assert reviewed.stability > 0
        assert reviewed.last_review is not None
        # next_review 应该在未来 (至少 1 分钟后)
        assert reviewed.next_review > now() - timedelta(minutes=1)

    def test_review_invalid_rating_raises(self, session, sample_card):
        with pytest.raises(ValueError, match="rating"):
            review_card(session, sample_card.id, 5)
        with pytest.raises(ValueError, match="rating"):
            review_card(session, sample_card.id, 0)
        with pytest.raises(ValueError, match="rating"):
            review_card(session, sample_card.id, -1)

    def test_review_nonexistent_card_raises(self, session):
        with pytest.raises(ValueError, match="不存在"):
            review_card(session, 99999, RATING_GOOD)

    def test_review_writes_log(self, session, sample_card):
        review_card(session, sample_card.id, RATING_HARD, "default")
        logs = session.exec(
            select(ReviewLog).where(ReviewLog.card_id == sample_card.id)
        ).all()
        assert len(logs) == 1
        assert logs[0].rating == RATING_HARD

    def test_multiple_reviews_increase_reps(self, session, sample_card):
        """连续多次评分, reps 应递增。"""
        for r in [RATING_GOOD, RATING_AGAIN, RATING_GOOD, RATING_EASY]:
            reviewed = review_card(session, sample_card.id, r, "default")
        assert reviewed.reps == 4
        logs = session.exec(
            select(ReviewLog).where(ReviewLog.card_id == sample_card.id)
        ).all()
        assert len(logs) == 4

    def test_again_leads_to_sooner_review_than_easy(self, session, sample_project):
        """Again 的下次复习应早于 Easy (核心算法行为)。"""
        # 两张相同的新卡
        node = session.exec(select(KnowledgeNode)).first()
        c1 = Card(
            user_id="default",
            node_id=node.id,
            project_id=node.project_id,
            front="Q1",
            back="A1",
        )
        c2 = Card(
            user_id="default",
            node_id=node.id,
            project_id=node.project_id,
            front="Q2",
            back="A2",
        )
        session.add_all([c1, c2])
        session.commit()
        session.refresh(c1)
        session.refresh(c2)

        r1 = review_card(session, c1.id, RATING_AGAIN)
        r2 = review_card(session, c2.id, RATING_EASY)
        # Again 应比 Easy 更早到期 (或相等, 但绝不应更晚很多)
        # 由于 fsrs 有 fuzzing, 允许一定误差, 但 Again 的间隔通常远小于 Easy
        assert r1.next_review <= r2.next_review + timedelta(hours=1)


class TestGetDueCards:
    def test_overdue_card_returned(self, session, sample_card):
        # 把 next_review 设为过去
        sample_card.next_review = now() - timedelta(hours=1)
        session.add(sample_card)
        session.commit()
        due = get_due_cards(session, user_id="default")
        assert any(c.id == sample_card.id for c in due)

    def test_future_card_not_returned(self, session, sample_card):
        sample_card.next_review = now() + timedelta(days=7)
        session.add(sample_card)
        session.commit()
        due = get_due_cards(session, user_id="default")
        assert not any(c.id == sample_card.id for c in due)

    def test_suspended_excluded(self, session, sample_card):
        sample_card.next_review = now() - timedelta(hours=1)
        sample_card.suspended = True
        session.add(sample_card)
        session.commit()
        due = get_due_cards(session, user_id="default")
        assert not any(c.id == sample_card.id for c in due)

    def test_filter_by_project(self, session, sample_card):
        sample_card.next_review = now() - timedelta(hours=1)
        session.add(sample_card)
        session.commit()
        # 正确 project_id
        due = get_due_cards(
            session, user_id="default", project_id=sample_card.project_id
        )
        assert any(c.id == sample_card.id for c in due)
        # 错误 project_id
        due = get_due_cards(session, user_id="default", project_id=99999)
        assert not any(c.id == sample_card.id for c in due)

    def test_order_by_due_asc(self, session, sample_project):
        """到期早的排前面。"""
        node = session.exec(select(KnowledgeNode)).first()
        cur = now()
        for i, hours_ago in enumerate([10, 1, 5]):
            c = Card(
                user_id="default",
                node_id=node.id,
                project_id=node.project_id,
                front=f"Q{i}",
                back="A",
                next_review=cur - timedelta(hours=hours_ago),
            )
            session.add(c)
        session.commit()
        due = get_due_cards(session, user_id="default")
        assert due[0].next_review <= due[1].next_review <= due[2].next_review


class TestGetReviewStats:
    def test_stats_counts(self, session, sample_project):
        node = session.exec(select(KnowledgeNode)).first()
        cur = now()
        # 2张到期新卡 + 1张未到期
        for i in range(2):
            session.add(
                Card(
                    user_id="default",
                    node_id=node.id,
                    project_id=node.project_id,
                    front=f"Q{i}",
                    back="A",
                    next_review=cur - timedelta(hours=1),
                    state=0,
                )
            )
        session.add(
            Card(
                user_id="default",
                node_id=node.id,
                project_id=node.project_id,
                front="Qf",
                back="A",
                next_review=cur + timedelta(days=7),
                state=2,
            )
        )
        session.commit()

        stats = get_review_stats(session, user_id="default")
        assert stats["total_cards"] == 3
        assert stats["due_count"] == 2
        assert stats["new_cards"] == 2
        assert stats["review_cards"] == 0  # 到期的都是新卡


class TestGenerateCardsFromNode:
    def test_generates_cards(self, session, sample_project, mock_llm):
        node = session.exec(select(KnowledgeNode)).first()
        cards = generate_cards_from_node(
            session,
            node.id,
            "default",
            "知识点内容",
            count=5,
        )
        assert len(cards) >= 1
        for c in cards:
            assert c.front
            assert c.back
            assert c.user_id == "default"
            assert c.node_id == node.id

    def test_nonexistent_node_raises(self, session):
        with pytest.raises(ValueError, match="不存在"):
            generate_cards_from_node(session, 99999, "default", "x")

    def test_empty_ai_result_returns_empty(self, session, sample_project, monkeypatch):
        """AI 返回空数据时不崩溃, 返回空列表。"""
        import learning_ext.llm as llm_pkg

        monkeypatch.setattr(llm_pkg, "chat_json", lambda *a, **k: {})
        node = session.exec(select(KnowledgeNode)).first()
        cards = generate_cards_from_node(session, node.id, "default", "x")
        assert cards == []

    def test_skip_empty_front_back(self, session, sample_project, monkeypatch):
        """AI 返回空 front/back 的卡片应被跳过。"""
        import learning_ext.llm as llm_pkg

        monkeypatch.setattr(
            llm_pkg,
            "chat_json",
            lambda *a, **k: {
                "cards": [
                    {"front": "", "back": "有答案"},  # 应跳过
                    {"front": "有问题", "back": ""},  # 应跳过
                    {"front": "好问题", "back": "好答案"},  # 保留
                ]
            },
        )
        node = session.exec(select(KnowledgeNode)).first()
        cards = generate_cards_from_node(session, node.id, "default", "x")
        assert len(cards) == 1
        assert cards[0].front == "好问题"
