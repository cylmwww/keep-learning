"""FSRS v6 间隔重复复习调度。

依赖：fsrs>=6 (pip install fsrs) —— Free Spaced Repetition Scheduler
比 Anki 经典 SM-2 算法先进 30%+。

fsrs v6 真实 API (已实测):
    - 类: Scheduler (非 FSRS, FSRS 在 v6 已重命名)
    - 调度: scheduler.review_card(card, rating) -> (new_card, review_log)
    - Card 字段: card_id, state, step, stability, difficulty, due, last_review
      (没有 reps 字段, 累计次数本系统自己维护)
    - State: Learning=1, Review=2, Relearning=3 (没有 New, 新卡是 Learning)
    - Rating: Again=1, Hard=2, Good=3, Easy=4

本系统的 state 字段语义:
    0 = 新卡 (本系统自定义, fsrs 无此状态, 第一次复习后转为 fsrs 状态)
    1 = Learning, 2 = Review, 3 = Relearning (与 fsrs 对齐)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlmodel import select

from learning_ext.db.models import Card, ReviewLog

logger = logging.getLogger(__name__)

# FSRS 评分常量 (与 fsrs.Rating 对齐)
RATING_AGAIN = 1
RATING_HARD = 2
RATING_GOOD = 3
RATING_EASY = 4

_VALID_RATINGS = (RATING_AGAIN, RATING_HARD, RATING_GOOD, RATING_EASY)

# 本系统 state 与 fsrs State 的映射
_OUR_NEW = 0  # 本系统自定义的"新卡"标记
_STATE_TO_FSRS = {
    _OUR_NEW: 1,  # 新卡进入 fsrs 时当作 Learning
    1: 1,  # Learning
    2: 2,  # Review
    3: 3,  # Relearning
}
_FSRS_TO_STATE = {1: 1, 2: 2, 3: 3}


def _get_scheduler():
    """懒加载 fsrs Scheduler。"""
    from fsrs import Scheduler

    return Scheduler()


def _to_aware_utc(dt):
    """naive datetime -> aware UTC; aware 原样; None -> now(utc)。给 fsrs 用。"""
    if dt is None:
        return datetime.now(timezone.utc)
    if hasattr(dt, "tzinfo") and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _to_fsrs_card(db_card: Card):
    """数据库 Card -> fsrs Card。DB 存 naive UTC, 传给 fsrs 前转 aware。"""
    from fsrs import Card as FSRSCard, State

    fsrs_state_val = _STATE_TO_FSRS.get(db_card.state, 1)
    try:
        fsrs_state = State(fsrs_state_val)
    except ValueError:
        fsrs_state = State.Learning

    return FSRSCard(
        card_id=db_card.id or 0,
        state=fsrs_state,
        step=db_card.step or 0,
        stability=db_card.stability if db_card.stability > 0 else None,
        difficulty=db_card.difficulty if db_card.difficulty > 0 else None,
        due=_to_aware_utc(db_card.next_review),
        last_review=_to_aware_utc(db_card.last_review),
    )


def _to_naive_utc(dt):
    """aware datetime -> naive UTC; naive 原样; None -> now。统一存储 tz 一致。"""
    if dt is None:
        return datetime.utcnow()
    if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _apply_fsrs_result(new_fcard, db_card: Card) -> None:
    """把 fsrs 调度结果回写到 DB Card (统一 naive UTC datetime)。"""
    db_card.stability = float(getattr(new_fcard, "stability", None) or 0.0)
    db_card.difficulty = float(getattr(new_fcard, "difficulty", None) or 0.0)
    db_card.state = _FSRS_TO_STATE.get(int(getattr(new_fcard, "state", 1)), 1)
    db_card.step = int(getattr(new_fcard, "step", 0) or 0)
    due = getattr(new_fcard, "due", None)
    if due is not None:
        db_card.next_review = _to_naive_utc(due)
    lr = getattr(new_fcard, "last_review", None)
    db_card.last_review = _to_naive_utc(lr) if lr else datetime.utcnow()


def find_log_by_request(session: Session, request_id: str) -> Optional[ReviewLog]:
    return session.exec(
        select(ReviewLog).where(ReviewLog.request_id == request_id)
    ).first()


def review_card(
    session: Session,
    card_id: int,
    rating: int,
    user_id: str = "default",
    *,
    request_id: Optional[str] = None,
) -> Card:
    """复习一张卡片并更新调度。

    Args:
        card_id: 卡片 id
        rating: 1(Again) 2(Hard) 3(Good) 4(Easy)
        request_id: 本次「展示→评分」的唯一 ID。同一 request_id 重复提交时
            直接返回当前卡片，不重复调度、不重复写日志。
    """
    if rating not in _VALID_RATINGS:
        raise ValueError(f"rating 必须为 {_VALID_RATINGS}，收到 {rating}")

    from fsrs import Rating

    card = session.get(Card, card_id)
    if card is None:
        raise ValueError(f"Card {card_id} 不存在")

    if request_id:
        existing = find_log_by_request(session, request_id)
        if existing is not None:
            if existing.card_id != card_id or existing.user_id != user_id:
                raise ValueError(f"request_id `{request_id}` 已被其他复习占用")
            return card

    prev_state = card.state
    prev_stability = card.stability
    prev_difficulty = card.difficulty

    fcard = _to_fsrs_card(card)
    scheduler = _get_scheduler()
    rating_enum = Rating(rating)

    try:
        new_fcard, _log = scheduler.review_card(fcard, rating_enum)
    except Exception as e:
        logger.exception("fsrs 调度失败, card_id=%s rating=%s", card_id, rating)
        raise RuntimeError(f"FSRS 调度失败: {e}") from e

    _apply_fsrs_result(new_fcard, card)
    card.reps = (card.reps or 0) + 1

    # 写复习日志
    session.add(
        ReviewLog(
            card_id=card.id,
            user_id=user_id,
            rating=rating,
            state=prev_state,
            stability=card.stability,
            difficulty=card.difficulty,
            request_id=request_id,
        )
    )
    try:
        session.commit()
    except IntegrityError:
        # 并发/双击落到唯一索引上：回滚后返回已存在的卡片状态
        session.rollback()
        if request_id and find_log_by_request(session, request_id) is not None:
            return session.get(Card, card_id)
        raise
    session.refresh(card)
    return card


def update_card(
    session: Session, card_id: int, front: str, back: str, user_id: str = "default"
) -> Card:
    """编辑卡片正反面（预览后可改正 AI 提炼的措辞）。"""
    front = (front or "").strip()
    back = (back or "").strip()
    if not front or not back:
        raise ValueError("卡片正面和背面都不能为空")

    card = session.get(Card, card_id)
    if card is None:
        raise ValueError(f"Card {card_id} 不存在")
    if card.user_id != user_id:
        raise ValueError(f"Card {card_id} 不属于用户 {user_id}")

    card.front = front
    card.back = back
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


def list_cards(
    session: Session,
    user_id: str = "default",
    *,
    project_id: Optional[int] = None,
    node_id: Optional[int] = None,
    limit: int = 500,
) -> List[Card]:
    """列出卡片（复习页预览/编辑用）。"""
    stmt = select(Card).where(Card.user_id == user_id)
    if project_id is not None:
        stmt = stmt.where(Card.project_id == project_id)
    if node_id is not None:
        stmt = stmt.where(Card.node_id == node_id)
    stmt = stmt.order_by(Card.created_at.desc(), Card.id.desc()).limit(limit)
    return list(session.exec(stmt).all())


def get_due_cards(
    session: Session,
    user_id: str = "default",
    *,
    project_id: Optional[int] = None,
    now: Optional[datetime] = None,
    limit: int = 100,
) -> List[Card]:
    """获取到期需要复习的卡片。"""
    now = now or datetime.utcnow()  # naive UTC, 与 DB 存储一致
    stmt = (
        select(Card)
        .where(Card.user_id == user_id)
        .where(Card.suspended == False)  # noqa: E712
        .where(Card.next_review <= now)
    )
    if project_id is not None:
        stmt = stmt.where(Card.project_id == project_id)
    stmt = stmt.order_by(Card.next_review.asc()).limit(limit)
    return list(session.exec(stmt).all())


def get_review_stats(
    session: Session,
    user_id: str = "default",
    project_id: Optional[int] = None,
) -> dict:
    """复习统计 (用于看板)。单次查询 + Python 聚合, 避免多次扫表。"""
    now = datetime.utcnow()  # naive UTC, 与 DB 存储一致
    stmt = select(Card).where(Card.user_id == user_id).where(Card.suspended == False)  # noqa: E712
    if project_id is not None:
        stmt = stmt.where(Card.project_id == project_id)
    all_cards = list(session.exec(stmt).all())
    due = [c for c in all_cards if c.next_review <= now]
    return {
        "due_count": len(due),
        "total_cards": len(all_cards),
        "new_cards": sum(1 for c in due if c.state == _OUR_NEW),
        "learning_cards": sum(1 for c in due if c.state == 1),
        "review_cards": sum(1 for c in due if c.state in (2, 3)),
    }


def generate_cards_from_node(
    session: Session,
    node_id: int,
    user_id: str,
    content: str,
    *,
    count: int = 5,
    model_name: Optional[str] = None,
) -> List[Card]:
    """AI 从知识点内容提炼复习卡片。不合规的单张卡片丢弃并记日志。"""
    from learning_ext.db.models import KnowledgeNode
    from learning_ext.llm import LLMOutputError, chat_json
    from learning_ext.llm.validate import as_str, require_str

    node = session.get(KnowledgeNode, node_id)
    if node is None:
        raise ValueError(f"Node {node_id} 不存在")

    prompt = f"""请基于以下知识点内容，提炼 {count} 张用于间隔重复复习的卡片。

【知识点】{node.title}
【说明】{node.description or ""}
【内容】
{content or "(无额外内容, 基于知识点标题和说明出题)"}

返回 JSON：{{"cards":[{{"front":"问题","back":"答案","card_type":"basic|cloze|concept"}}]}}
只返回 JSON。"""

    result = chat_json(prompt, model_name=model_name)
    # 兼容 list 或 {"cards": [...]}
    if isinstance(result, list):
        items = result
    elif isinstance(result, dict):
        items = result.get("cards") or result.get("items") or []
    else:
        items = []

    if not items:
        logger.warning("AI 未返回有效卡片数据")
        return []

    cards: List[Card] = []
    for i, item in enumerate(items[:count]):
        try:
            if not isinstance(item, dict):
                raise LLMOutputError(f"cards[{i}] 应为 object，实际 {type(item).__name__}")
            front = require_str(item.get("front"), f"cards[{i}].front", max_len=2000)
            back = require_str(item.get("back"), f"cards[{i}].back", max_len=4000)
            card_type = as_str(
                item.get("card_type"), f"cards[{i}].card_type", default="basic"
            )
        except LLMOutputError as e:
            logger.warning("丢弃第 %s 张不合规的卡片: %s", i + 1, e)
            continue
        card = Card(
            user_id=user_id,
            node_id=node_id,
            project_id=node.project_id,
            front=front,
            back=back,
            card_type=card_type or "basic",
        )
        session.add(card)
        cards.append(card)
    if cards:
        session.commit()
    return cards
