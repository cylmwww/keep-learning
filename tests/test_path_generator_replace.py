from __future__ import annotations

from sqlmodel import select

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
from learning_ext.path_generator import replace_project_roadmap


def test_replace_project_roadmap_clears_old_generated_learning_data(session):
    from learning_ext.dashboard.service import seed_demo_learning_data

    project = seed_demo_learning_data(session)
    replacement = {
        "summary": "Replacement roadmap",
        "stages": [{"name": "Base", "stage": "base", "goal": "Rebuild"}],
        "nodes": [
            {
                "code": "1.1",
                "title": "New start",
                "description": "Fresh node",
                "stage": "base",
                "est_hours": 1,
                "difficulty": 1,
                "prerequisites": [],
            },
            {
                "code": "1.2",
                "title": "New follow-up",
                "description": "Fresh dependent node",
                "stage": "base",
                "est_hours": 2,
                "difficulty": 2,
                "prerequisites": ["1.1"],
            },
        ],
    }

    replaced = replace_project_roadmap(session, project.id, replacement)

    assert replaced.id == project.id
    assert session.get(LearningProject, project.id) is not None
    nodes = session.exec(
        select(KnowledgeNode).where(KnowledgeNode.project_id == project.id)
    ).all()
    edges = session.exec(
        select(KnowledgeEdge).where(KnowledgeEdge.project_id == project.id)
    ).all()
    assert [node.code for node in sorted(nodes, key=lambda n: n.code)] == [
        "1.1",
        "1.2",
    ]
    assert len(edges) == 1
    for model in (
        Card,
        DailyReport,
        NodeNote,
        NodeResource,
        ProgressRecord,
        Quiz,
        QuizAttempt,
        QuizQuestion,
        ReviewLog,
        Task,
    ):
        assert session.exec(select(model)).all() == []
