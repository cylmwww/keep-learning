from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_sqlite_migration_backfills_card_step_column():
    from learning_ext.bootstrap import _ensure_sqlite_columns

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE le_card (
                    id INTEGER PRIMARY KEY,
                    user_id VARCHAR NOT NULL,
                    front VARCHAR NOT NULL,
                    back VARCHAR NOT NULL
                )
                """
            )
        )

    _ensure_sqlite_columns(engine)
    _ensure_sqlite_columns(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("le_card")}
    assert {"step", "due_order", "suspended"}.issubset(columns)


def _legacy_engine():
    """旧版库：没有 score / error_type / request_id，也没有唯一索引。"""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE le_quiz_attempt (
                    id INTEGER PRIMARY KEY,
                    question_id INTEGER NOT NULL,
                    user_id VARCHAR NOT NULL,
                    user_answer VARCHAR NOT NULL,
                    is_correct BOOLEAN,
                    attempted_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE le_reviewlog (
                    id INTEGER PRIMARY KEY,
                    card_id INTEGER NOT NULL,
                    user_id VARCHAR NOT NULL,
                    rating INTEGER NOT NULL,
                    state INTEGER,
                    stability REAL,
                    difficulty REAL,
                    reviewed_at DATETIME
                )
                """
            )
        )
    return engine


def test_backfills_dedup_columns_on_existing_databases():
    """老库升级后必须拿到去重所需的列，历史行不受影响。"""
    from learning_ext.bootstrap import _ensure_sqlite_columns

    engine = _legacy_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO le_quiz_attempt (question_id, user_id, user_answer, is_correct)"
                " VALUES (1, 'default', '历史作答', 1)"
            )
        )

    _ensure_sqlite_columns(engine)
    _ensure_sqlite_columns(engine)  # 幂等

    attempt_columns = {c["name"] for c in inspect(engine).get_columns("le_quiz_attempt")}
    assert {"score", "error_type", "request_id"}.issubset(attempt_columns)
    review_columns = {c["name"] for c in inspect(engine).get_columns("le_reviewlog")}
    assert "request_id" in review_columns

    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT score, error_type, request_id FROM le_quiz_attempt WHERE id = 1")
        ).one()
    assert row == (0.0, "", None)


def test_creates_unique_indexes_for_dedup():
    from learning_ext.bootstrap import _ensure_sqlite_columns

    engine = _legacy_engine()
    _ensure_sqlite_columns(engine)

    for table, index in (
        ("le_quiz_attempt", "ix_le_quiz_attempt_request_id"),
        ("le_reviewlog", "ix_le_reviewlog_request_id"),
    ):
        names = {i["name"] for i in inspect(engine).get_indexes(table)}
        assert index in names, f"{table} 缺少唯一索引 {index}"


def test_duplicate_request_id_is_rejected_by_the_database():
    """幂等性最终靠唯一索引兜底，不能只靠应用层查一次。"""
    from learning_ext.bootstrap import _ensure_sqlite_columns

    engine = _legacy_engine()
    _ensure_sqlite_columns(engine)

    insert = text(
        "INSERT INTO le_reviewlog (card_id, user_id, rating, request_id)"
        " VALUES (1, 'default', 3, 'req-1')"
    )
    with engine.begin() as conn:
        conn.execute(insert)

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(insert)


def test_legacy_null_request_ids_do_not_collide():
    """历史行的 request_id 是 NULL；SQLite 唯一索引视多个 NULL 为互不相同。"""
    from learning_ext.bootstrap import _ensure_sqlite_columns

    engine = _legacy_engine()
    _ensure_sqlite_columns(engine)

    insert = text(
        "INSERT INTO le_reviewlog (card_id, user_id, rating, request_id)"
        " VALUES (1, 'default', 3, NULL)"
    )
    with engine.begin() as conn:
        conn.execute(insert)
        conn.execute(insert)
        count = conn.execute(text("SELECT COUNT(*) FROM le_reviewlog")).scalar()
    assert count == 2
