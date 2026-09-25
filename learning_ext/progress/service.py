"""学习进度跟踪 + 掌握度模型。

掌握度 mastery (0.0-1.0) 综合三个信号：
    1. 测验正确率 (quiz score)
    2. FSRS 卡片稳定性 (memory stability)
    3. 学习进度 (status 推进)

每次测验/复习/状态变更后自动更新，回流到"查漏补缺"选题。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlmodel import func, select

from learning_ext.db.models import (
    Card,
    KnowledgeNode,
    ProgressRecord,
    QuizAttempt,
    QuizQuestion,
)


def update_mastery(
    session: Session,
    node_id: int,
    *,
    correct: Optional[bool] = None,
    commit: bool = True,
) -> float:
    """重新计算并更新某知识点的综合掌握度。

    掌握度公式 (加权)：
        mastery = 0.4 * quiz_score + 0.3 * memory_score + 0.3 * progress_score
    其中：
        quiz_score    = 该节点相关题目最近10次的正确率
        memory_score  = min(1, avg(stability) / 30)  # 稳定性30天以上算满分
        progress_score = status 推进度 (pending0 learning0.3 reviewing0.6 weak0.4 mastered1)

    Args:
        correct: 若提供，先记录一条 quiz 进度，再算
        commit: False 时只 flush, 由调用方在自己的事务边界内提交
                (作答记录 + 掌握度回写必须是同一个事务)
    """
    node = session.get(KnowledgeNode, node_id)
    if node is None:
        raise ValueError(f"Node {node_id} not found")

    if correct is not None:
        # 记录进度时序
        session.add(
            ProgressRecord(
                user_id="default",  # TODO: 从上下文传入
                project_id=node.project_id,
                node_id=node_id,
                metric="quiz",
                value=1.0 if correct else 0.0,
            )
        )

    # 1. quiz_score: 该节点题目的最近正确率
    quiz_score = _calc_quiz_score(session, node_id)

    # 2. memory_score: 关联卡片的平均稳定性
    memory_score = _calc_memory_score(session, node_id)

    # 3. progress_score: 状态推进
    progress_score = {
        "pending": 0.0,
        "learning": 0.3,
        "reviewing": 0.6,
        "weak": 0.4,
        "mastered": 1.0,
    }.get(node.status, 0.0)

    mastery = 0.4 * quiz_score + 0.3 * memory_score + 0.3 * progress_score
    mastery = max(0.0, min(1.0, mastery))

    node.mastery = mastery
    # 掌握度高自动转 mastered
    if mastery >= 0.85 and node.status != "mastered":
        node.status = "mastered"
    # 测验错多转 weak
    elif correct is False and mastery < 0.5 and node.status not in ("mastered",):
        node.status = "weak"

    if commit:
        session.commit()
    else:
        session.flush()
    return mastery


def _calc_quiz_score(session: Session, node_id: int) -> float:
    """该节点题目的最近 10 次答题正确率。"""
    stmt = (
        select(QuizAttempt)
        .join(QuizQuestion, QuizAttempt.question_id == QuizQuestion.id)
        .where(QuizQuestion.node_id == node_id)
        .order_by(QuizAttempt.attempted_at.desc())
        .limit(10)
    )
    attempts = list(session.exec(stmt).all())
    if not attempts:
        return 0.0
    correct = sum(1 for a in attempts if a.is_correct)
    return correct / len(attempts)


def _calc_memory_score(session: Session, node_id: int) -> float:
    """关联卡片的平均稳定性得分。"""
    stmt = select(Card).where(Card.node_id == node_id)
    cards = list(session.exec(stmt).all())
    if not cards:
        return 0.0
    avg_stab = sum(c.stability for c in cards) / len(cards)
    return min(1.0, avg_stab / 30.0)


def record_study_time(
    session: Session,
    user_id: str,
    project_id: int,
    node_id: Optional[int],
    minutes: int,
):
    """记录学习时长 (用于热力图/日报)。"""
    session.add(
        ProgressRecord(
            user_id=user_id,
            project_id=project_id,
            node_id=node_id,
            metric="study_minutes",
            value=float(minutes),
        )
    )
    session.commit()


def get_heatmap_data(
    session: Session,
    user_id: str,
    *,
    days: int = 90,
    project_id: Optional[int] = None,
) -> list[dict]:
    """获取学习热力图数据 (最近 N 天每日学习分钟数)。"""
    start = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = (
        select(
            func.date(ProgressRecord.recorded_at).label("day"),
            func.sum(ProgressRecord.value).label("minutes"),
        )
        .where(ProgressRecord.user_id == user_id)
        .where(ProgressRecord.metric == "study_minutes")
        .where(ProgressRecord.recorded_at >= start)
        .group_by(func.date(ProgressRecord.recorded_at))
    )
    if project_id is not None:
        stmt = stmt.where(ProgressRecord.project_id == project_id)
    rows = session.exec(stmt).all()
    return [{"date": str(r[0]), "minutes": float(r[1] or 0)} for r in rows]


def get_project_overview(session: Session, project_id: int) -> dict:
    """项目总览 (用于看板顶部卡片)。"""
    nodes = session.exec(
        select(KnowledgeNode).where(KnowledgeNode.project_id == project_id)
    ).all()
    total = len(nodes)
    if total == 0:
        return {
            "total": 0,
            "mastered": 0,
            "mastered_pct": 0,
            "avg_mastery": 0,
            "total_hours": 0,
        }

    mastered = sum(1 for n in nodes if n.status == "mastered")
    avg_mastery = sum(n.mastery for n in nodes) / total
    total_hours = sum(n.est_hours for n in nodes)

    return {
        "total": total,
        "mastered": mastered,
        "mastered_pct": mastered / total,
        "avg_mastery": avg_mastery,
        "total_hours": total_hours,
    }
