"""
learning_ext.db - 学习特化数据模型

所有模型复用 Kotaemon 的 SQLModel engine (ktem.db.engine.engine)，
建表时调用 SQLModel.metadata.create_all(engine) 即可一并创建。
"""

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

__all__ = [
    "LearningProject",
    "KnowledgeNode",
    "KnowledgeEdge",
    "Card",
    "ReviewLog",
    "Quiz",
    "QuizQuestion",
    "QuizAttempt",
    "ProgressRecord",
    "Task",
    "DailyReport",
    "NodeNote",
    "NodeResource",
]
