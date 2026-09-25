from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlmodel import Session, select

from learning_ext.db.models import (
    Card,
    DailyReport,
    KnowledgeEdge,
    KnowledgeNode,
    LearningProject,
    NodeNote,
    NodeResource,
    ProgressRecord,
    Quiz,
    QuizAttempt,
    QuizQuestion,
    ReviewLog,
    Task,
)
from learning_ext.project_ops import delete_project

DEMO_TITLE = "学习看板测试项目"


def seed_demo_learning_data(session: Session, user_id: str = "default") -> LearningProject:
    existing = session.exec(
        select(LearningProject)
        .where(LearningProject.user_id == user_id)
        .where(LearningProject.title == DEMO_TITLE)
    ).all()
    for project in existing:
        if project.id is not None:
            delete_project(session, project.id)

    now = datetime.utcnow()
    roadmap = {
        "summary": DEMO_TITLE,
        "stages": [
            {"name": "基础", "stage": "base", "goal": "建立概念框架"},
            {"name": "强化", "stage": "strengthen", "goal": "做题和项目练习"},
            {"name": "冲刺", "stage": "sprint", "goal": "查漏补缺和输出"},
        ],
        "nodes": [
            {"code": "1.1", "title": "学习目标拆解", "stage": "base"},
            {"code": "1.2", "title": "核心概念地图", "stage": "base"},
            {"code": "1.3", "title": "最小实践闭环", "stage": "base"},
            {"code": "2.1", "title": "案例分析", "stage": "strengthen"},
            {"code": "2.2", "title": "错题复盘", "stage": "strengthen"},
            {"code": "2.3", "title": "记忆卡片提炼", "stage": "strengthen"},
            {"code": "3.1", "title": "综合测验", "stage": "sprint"},
            {"code": "3.2", "title": "费曼输出", "stage": "sprint"},
        ],
    }
    project = LearningProject(
        user_id=user_id,
        title=DEMO_TITLE,
        topic="测试学习看板数据",
        background="用于验证学习看板的统计、热力图、日报和复习指标",
        goal="快速看出项目进度、掌握度和近 7 天学习强度",
        weekly_hours=8,
        roadmap_json=json.dumps(roadmap, ensure_ascii=False),
        status="active",
        created_at=now - timedelta(days=18),
        updated_at=now,
    )
    session.add(project)
    session.flush()

    node_specs = [
        ("1.1", "学习目标拆解", "base", "mastered", 0.92, 1.5, 2),
        ("1.2", "核心概念地图", "base", "mastered", 0.88, 2.0, 2),
        ("1.3", "最小实践闭环", "base", "learning", 0.56, 2.5, 3),
        ("2.1", "案例分析", "strengthen", "learning", 0.48, 2.0, 3),
        ("2.2", "错题复盘", "strengthen", "weak", 0.32, 1.5, 4),
        ("2.3", "记忆卡片提炼", "strengthen", "pending", 0.18, 1.5, 3),
        ("3.1", "综合测验", "sprint", "pending", 0.08, 2.0, 4),
        ("3.2", "费曼输出", "sprint", "skipped", 0.0, 1.0, 2),
    ]
    nodes: list[KnowledgeNode] = []
    for code, title, stage, status, mastery, hours, difficulty in node_specs:
        node = KnowledgeNode(
            project_id=project.id,
            code=code,
            title=title,
            description=(
                f"## {title}\n\n这是用于测试学习看板的课程内容。"
                "它包含足够长的说明文本，便于工作台、看板和划词解释功能读取真实课程数据。"
            ),
            stage=stage,
            status=status,
            mastery=mastery,
            est_hours=hours,
            difficulty=difficulty,
            created_at=now - timedelta(days=18),
        )
        session.add(node)
        session.flush()
        nodes.append(node)

    code_to_node = {node.code: node for node in nodes}
    for source, target in [
        ("1.2", "1.1"),
        ("1.3", "1.2"),
        ("2.1", "1.3"),
        ("2.2", "2.1"),
        ("2.3", "2.2"),
        ("3.1", "2.3"),
        ("3.2", "3.1"),
    ]:
        session.add(
            KnowledgeEdge(
                project_id=project.id,
                source_id=code_to_node[source].id,
                target_id=code_to_node[target].id,
            )
        )

    for i, node in enumerate(nodes[:6], start=1):
        card = Card(
            user_id=user_id,
            project_id=project.id,
            node_id=node.id,
            front=f"{node.title} 的关键问题是什么？",
            back=f"{node.title} 的回答要点包括定义、用途和一个例子。",
            card_type="concept",
            stability=4.0 + i * 3,
            difficulty=2.0 + i * 0.4,
            reps=i,
            state=2 if i <= 4 else 1,
            last_review=now - timedelta(days=i),
            next_review=now - timedelta(days=1) if i % 2 else now + timedelta(days=i),
            created_at=now - timedelta(days=14),
        )
        session.add(card)
        session.flush()
        session.add(
            ReviewLog(
                card_id=card.id,
                user_id=user_id,
                rating=3 if i % 3 else 2,
                state=card.state,
                stability=card.stability,
                difficulty=card.difficulty,
                reviewed_at=now - timedelta(days=i % 7),
            )
        )

    quiz = Quiz(
        project_id=project.id,
        user_id=user_id,
        node_id=nodes[4].id,
        title="学习看板测试测验",
        quiz_type="mixed",
        scope_node_ids=",".join(str(node.id) for node in nodes[:5]),
        created_at=now - timedelta(days=3),
    )
    session.add(quiz)
    session.flush()
    for i, node in enumerate(nodes[:5], start=1):
        question = QuizQuestion(
            quiz_id=quiz.id,
            node_id=node.id,
            qtype="short",
            stem=f"解释 {node.title}",
            answer="给出定义和例子",
            explanation="测试看板用题目",
            difficulty=node.difficulty,
        )
        session.add(question)
        session.flush()
        session.add(
            QuizAttempt(
                question_id=question.id,
                user_id=user_id,
                user_answer="测试答案",
                is_correct=i not in (4, 5),
                feedback="测试反馈",
                attempted_at=now - timedelta(days=i),
            )
        )

    for i, minutes in enumerate([35, 20, 45, 0, 55, 30, 25, 15, 40, 60, 10, 50]):
        if minutes <= 0:
            continue
        session.add(
            ProgressRecord(
                user_id=user_id,
                project_id=project.id,
                node_id=nodes[i % len(nodes)].id,
                metric="study_minutes",
                value=float(minutes),
                recorded_at=now - timedelta(days=i),
            )
        )
    for node in nodes[:5]:
        session.add(
            ProgressRecord(
                user_id=user_id,
                project_id=project.id,
                node_id=node.id,
                metric="mastery",
                value=node.mastery,
                recorded_at=now - timedelta(days=2),
            )
        )

    session.add(
        DailyReport(
            user_id=user_id,
            project_id=project.id,
            report_date=now,
            content=(
                "### 今日学习日报\n\n"
                "- 已完成 2 个基础知识点复习\n"
                "- 薄弱点集中在错题复盘\n"
                "- 明天建议优先完成记忆卡片提炼"
            ),
            study_minutes=95,
            cards_reviewed=6,
            nodes_progressed=2,
            created_at=now,
        )
    )
    session.add(
        Task(
            project_id=project.id,
            node_id=None,
            title="测试环境配置",
            description="用于看板测试的环境任务",
            task_type="env",
            status="done",
        )
    )
    for node in nodes[:3]:
        session.add(
            NodeNote(
                user_id=user_id,
                project_id=project.id,
                node_id=node.id,
                content=f"关于 {node.title} 的测试笔记。",
                created_at=now - timedelta(days=1),
                updated_at=now,
            )
        )
        session.add(
            NodeResource(
                project_id=project.id,
                node_id=node.id,
                title=f"{node.title} 参考资料",
                url="https://example.com/demo",
                rtype="article",
                description="测试看板用参考资料",
            )
        )

    session.commit()
    session.refresh(project)
    return project


def build_dashboard_data(
    session: Session,
    user_id: str = "default",
    project_id: int | None = None,
) -> dict:
    projects = list(
        session.exec(
            select(LearningProject)
            .where(LearningProject.user_id == user_id)
            .order_by(LearningProject.id.desc())
        ).all()
    )
    if project_id is None and projects:
        project_id = projects[0].id

    nodes_stmt = select(KnowledgeNode)
    progress_stmt = select(ProgressRecord).where(ProgressRecord.user_id == user_id)
    reports_stmt = select(DailyReport).where(DailyReport.user_id == user_id)
    cards_stmt = select(Card).where(Card.user_id == user_id)
    if project_id is not None:
        nodes_stmt = nodes_stmt.where(KnowledgeNode.project_id == project_id)
        progress_stmt = progress_stmt.where(ProgressRecord.project_id == project_id)
        reports_stmt = reports_stmt.where(DailyReport.project_id == project_id)
        cards_stmt = cards_stmt.where(Card.project_id == project_id)

    nodes = list(session.exec(nodes_stmt).all())
    progress = list(session.exec(progress_stmt).all())
    cards = list(session.exec(cards_stmt).all())
    reports = list(
        session.exec(reports_stmt.order_by(DailyReport.report_date.desc())).all()
    )
    now = datetime.utcnow()
    week_start = now - timedelta(days=7)
    week_minutes = sum(
        p.value
        for p in progress
        if p.metric == "study_minutes" and p.recorded_at >= week_start
    )
    total_nodes = len(nodes)
    mastered_nodes = sum(1 for node in nodes if node.status == "mastered")
    avg_mastery = sum(node.mastery for node in nodes) / total_nodes if nodes else 0.0
    status_counts = {
        "mastered": mastered_nodes,
        "learning": sum(1 for node in nodes if node.status == "learning"),
        "weak": sum(1 for node in nodes if node.status == "weak"),
        "pending": sum(1 for node in nodes if node.status == "pending"),
        "skipped": sum(1 for node in nodes if node.status == "skipped"),
    }

    heatmap = []
    for days_ago in range(13, -1, -1):
        day = (now - timedelta(days=days_ago)).date()
        minutes = sum(
            p.value
            for p in progress
            if p.metric == "study_minutes" and p.recorded_at.date() == day
        )
        heatmap.append({"date": day.isoformat(), "minutes": minutes})

    return {
        "project_id": project_id,
        "projects": [
            (f"#{p.id} {p.title}", str(p.id)) for p in projects if p.id is not None
        ],
        "metrics": {
            "total_nodes": total_nodes,
            "mastered_nodes": mastered_nodes,
            "avg_mastery": avg_mastery,
            "week_minutes": week_minutes,
            "due_cards": sum(1 for card in cards if card.next_review <= now),
            "total_cards": len(cards),
        },
        "status_counts": status_counts,
        "heatmap": heatmap,
        "latest_report": reports[0].content if reports else "*暂无学习日报*",
    }
