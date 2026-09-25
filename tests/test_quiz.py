"""测验 service 测试。"""

from __future__ import annotations

import json

import pytest
from sqlmodel import select

from learning_ext.db.models import (
    KnowledgeNode,
    Quiz,
    QuizAttempt,
    QuizQuestion,
)
from learning_ext.llm import LLMOutputError
from learning_ext.quiz import (
    create_retry_quiz,
    generate_quiz,
    get_quiz_summary,
    get_weak_nodes,
    grade_answer,
    select_scope_nodes,
)


def _make_question(session, quiz, *, qtype="choice", answer="A", options=None):
    q = QuizQuestion(
        quiz_id=quiz.id,
        node_id=None,
        qtype=qtype,
        stem="测试题",
        options=json.dumps(
            options if options is not None else ["A. 甲", "B. 乙", "C. 丙", "D. 丁"],
            ensure_ascii=False,
        ),
        answer=answer,
        explanation="因为",
        difficulty=3,
    )
    session.add(q)
    session.commit()
    session.refresh(q)
    return q


def _make_quiz(session, project_id=None) -> Quiz:
    quiz = Quiz(user_id="default", project_id=project_id, title="手工测验")
    session.add(quiz)
    session.commit()
    session.refresh(quiz)
    return quiz


class TestGenerateQuiz:
    def test_generates_quiz_with_questions(self, session, sample_project, mock_llm):
        node = session.exec(select(KnowledgeNode)).first()
        quiz = generate_quiz(
            session,
            "default",
            [node.id],
            project_id=sample_project.id,
            count=1,
            qtype="choice",
        )
        assert quiz.id is not None
        assert quiz.user_id == "default"
        questions = session.exec(
            select(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id)
        ).all()
        assert len(questions) >= 1

    def test_empty_node_ids_raises(self, session):
        with pytest.raises(ValueError, match="未找到"):
            generate_quiz(session, "default", [])

    def test_nonexistent_node_ids_raises(self, session):
        with pytest.raises(ValueError, match="未找到"):
            generate_quiz(session, "default", [99999])

    def test_question_links_back_to_node(self, session, sample_project, mock_llm):
        """题目必须挂到知识点上, 否则掌握度永远回写不了。"""
        node = session.exec(select(KnowledgeNode)).first()
        quiz = generate_quiz(session, "default", [node.id], project_id=sample_project.id)
        questions = session.exec(
            select(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id)
        ).all()
        assert questions
        assert all(q.node_id == node.id for q in questions)

    def test_invalid_qtype_raises(self, session, sample_project):
        node = session.exec(select(KnowledgeNode)).first()
        with pytest.raises(ValueError, match="qtype"):
            generate_quiz(session, "default", [node.id], qtype="essay")

    def test_invalid_count_raises(self, session, sample_project):
        node = session.exec(select(KnowledgeNode)).first()
        with pytest.raises(ValueError, match="count"):
            generate_quiz(session, "default", [node.id], count=0)

    def test_malformed_questions_are_dropped(self, session, sample_project, monkeypatch):
        """类型不符的单题丢弃, 合规的照常入库。"""
        import learning_ext.quiz.service as svc

        monkeypatch.setattr(
            svc,
            "chat_json",
            lambda *a, **k: [
                {
                    "qtype": "choice",
                    "stem": "好题",
                    "options": ["A. 甲", "B. 乙"],
                    "answer": "A",
                    "difficulty": 2,
                },
                {
                    "qtype": "choice",
                    "stem": "difficulty 是字符串",
                    "options": ["A. 甲", "B. 乙"],
                    "answer": "A",
                    "difficulty": "3",
                },
                {"qtype": "essay", "stem": "题型非法", "answer": "x"},
            ],
        )
        node = session.exec(select(KnowledgeNode)).first()
        quiz = generate_quiz(session, "default", [node.id], project_id=sample_project.id)
        questions = session.exec(
            select(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id)
        ).all()
        assert [q.stem for q in questions] == ["好题"]

    def test_all_questions_malformed_raises(self, session, sample_project, monkeypatch):
        import learning_ext.quiz.service as svc

        monkeypatch.setattr(svc, "chat_json", lambda *a, **k: [{"qtype": "essay"}])
        node = session.exec(select(KnowledgeNode)).first()
        with pytest.raises(LLMOutputError, match="全部格式不合规"):
            generate_quiz(session, "default", [node.id], project_id=sample_project.id)

    def test_non_list_result_raises(self, session, sample_project, monkeypatch):
        import learning_ext.quiz.service as svc

        monkeypatch.setattr(svc, "chat_json", lambda *a, **k: "不是 JSON 结构")
        node = session.exec(select(KnowledgeNode)).first()
        with pytest.raises(LLMOutputError):
            generate_quiz(session, "default", [node.id], project_id=sample_project.id)

    def test_choice_answer_must_be_a_valid_letter(
        self, session, sample_project, monkeypatch
    ):
        import learning_ext.quiz.service as svc

        monkeypatch.setattr(
            svc,
            "chat_json",
            lambda *a, **k: [
                {
                    "qtype": "choice",
                    "stem": "答案不在选项里",
                    "options": ["A. 甲", "B. 乙"],
                    "answer": "Z",
                    "difficulty": 2,
                }
            ],
        )
        node = session.exec(select(KnowledgeNode)).first()
        with pytest.raises(LLMOutputError):
            generate_quiz(session, "default", [node.id], project_id=sample_project.id)


class TestGradeChoice:
    """选择题走确定性比较，不发 LLM 请求。"""

    def test_correct_letter(self, session, sample_project):
        quiz = _make_quiz(session, sample_project.id)
        q = _make_question(session, quiz)
        attempt = grade_answer(session, q.id, "A", "default")
        assert attempt.is_correct is True
        assert attempt.score == 1.0
        assert attempt.error_type == ""

    def test_wrong_letter(self, session, sample_project):
        quiz = _make_quiz(session, sample_project.id)
        q = _make_question(session, quiz)
        attempt = grade_answer(session, q.id, "C", "default")
        assert attempt.is_correct is False
        assert attempt.score == 0.0
        assert attempt.error_type == "concept_unclear"

    def test_full_option_text_is_accepted(self, session, sample_project):
        quiz = _make_quiz(session, sample_project.id)
        q = _make_question(session, quiz)
        attempt = grade_answer(session, q.id, "A. 甲", "default")
        assert attempt.is_correct is True

    def test_blank_is_recorded_as_blank(self, session, sample_project):
        quiz = _make_quiz(session, sample_project.id)
        q = _make_question(session, quiz)
        attempt = grade_answer(session, q.id, "   ", "default")
        assert attempt.is_correct is False
        assert attempt.error_type == "blank"

    def test_choice_grading_does_not_call_llm(self, session, sample_project, monkeypatch):
        import learning_ext.quiz.service as svc

        def _boom(*a, **k):
            raise AssertionError("选择题不应调用 LLM")

        monkeypatch.setattr(svc, "chat_json", _boom)
        quiz = _make_quiz(session, sample_project.id)
        q = _make_question(session, quiz)
        assert grade_answer(session, q.id, "A", "default").is_correct is True


class TestGradeOpen:
    """主观题按要点给分，is_correct 由 score 与题型阈值算出。"""

    def _quiz_with(self, session, project_id, qtype):
        quiz = _make_quiz(session, project_id)
        return _make_question(session, quiz, qtype=qtype, answer="要点一；要点二")

    def test_partial_score_is_stored(self, session, sample_project, monkeypatch):
        import learning_ext.quiz.service as svc

        monkeypatch.setattr(
            svc,
            "chat_json",
            lambda *a, **k: {
                "score": 0.5,
                "missed_points": ["要点二"],
                "error_type": "incomplete",
                "feedback": "漏了一个要点",
            },
        )
        q = self._quiz_with(session, sample_project.id, "short")
        attempt = grade_answer(session, q.id, "我的答案", "default")
        assert attempt.score == 0.5
        assert attempt.is_correct is False
        assert attempt.error_type == "incomplete"
        assert "要点二" in attempt.feedback

    def test_score_above_threshold_is_correct(self, session, sample_project, monkeypatch):
        import learning_ext.quiz.service as svc

        monkeypatch.setattr(
            svc,
            "chat_json",
            lambda *a, **k: {
                "score": 0.8,
                "missed_points": [],
                "error_type": "incomplete",
                "feedback": "基本正确",
            },
        )
        q = self._quiz_with(session, sample_project.id, "short")
        attempt = grade_answer(session, q.id, "答案", "default")
        assert attempt.is_correct is True
        assert attempt.error_type == ""  # 判对时错误类型清空

    def test_string_score_is_rejected(self, session, sample_project, monkeypatch):
        """`"0.9"` 这种字符串得分在入库前被拒绝, 不静默参与比较。"""
        import learning_ext.quiz.service as svc

        monkeypatch.setattr(
            svc,
            "chat_json",
            lambda *a, **k: {
                "score": "0.9",
                "missed_points": [],
                "error_type": "incomplete",
                "feedback": "x",
            },
        )
        q = self._quiz_with(session, sample_project.id, "short")
        with pytest.raises(LLMOutputError, match="score"):
            grade_answer(session, q.id, "答案", "default")
        assert session.exec(select(QuizAttempt)).all() == []

    def test_unknown_error_type_is_rejected(self, session, sample_project, monkeypatch):
        import learning_ext.quiz.service as svc

        monkeypatch.setattr(
            svc,
            "chat_json",
            lambda *a, **k: {
                "score": 0.2,
                "missed_points": [],
                "error_type": "瞎写的类型",
                "feedback": "x",
            },
        )
        q = self._quiz_with(session, sample_project.id, "short")
        with pytest.raises(LLMOutputError, match="error_type"):
            grade_answer(session, q.id, "答案", "default")

    def test_blank_short_answer_skips_llm(self, session, sample_project, monkeypatch):
        import learning_ext.quiz.service as svc

        def _boom(*a, **k):
            raise AssertionError("未作答不该调用 LLM")

        monkeypatch.setattr(svc, "chat_json", _boom)
        q = self._quiz_with(session, sample_project.id, "short")
        attempt = grade_answer(session, q.id, "", "default")
        assert attempt.error_type == "blank"
        assert attempt.is_correct is False


class TestSubmissionDedup:
    def test_same_request_id_creates_one_attempt(self, session, sample_project):
        quiz = _make_quiz(session, sample_project.id)
        q = _make_question(session, quiz)
        rid = "req-1"
        first = grade_answer(session, q.id, "A", "default", request_id=rid)
        second = grade_answer(session, q.id, "C", "default", request_id=rid)
        assert first.id == second.id
        assert second.is_correct is True  # 仍然是第一次的结果
        attempts = session.exec(select(QuizAttempt)).all()
        assert len(attempts) == 1

    def test_mastery_written_once_per_request(self, session, sample_project):
        node = session.exec(select(KnowledgeNode)).first()
        quiz = _make_quiz(session, sample_project.id)
        q = _make_question(session, quiz)
        q.node_id = node.id
        session.add(q)
        session.commit()

        rid = "req-mastery"
        grade_answer(session, q.id, "A", "default", request_id=rid)
        session.refresh(node)
        first_mastery = node.mastery
        grade_answer(session, q.id, "A", "default", request_id=rid)
        session.refresh(node)
        assert node.mastery == first_mastery

    def test_request_id_mismatch_raises(self, session, sample_project):
        quiz = _make_quiz(session, sample_project.id)
        q1 = _make_question(session, quiz)
        q2 = _make_question(session, quiz)
        grade_answer(session, q1.id, "A", "default", request_id="req-x")
        with pytest.raises(ValueError, match="占用"):
            grade_answer(session, q2.id, "A", "default", request_id="req-x")

    def test_different_request_ids_create_two_attempts(self, session, sample_project):
        quiz = _make_quiz(session, sample_project.id)
        q = _make_question(session, quiz)
        grade_answer(session, q.id, "A", "default", request_id="req-a")
        grade_answer(session, q.id, "B", "default", request_id="req-b")
        assert len(session.exec(select(QuizAttempt)).all()) == 2

    def test_llm_failure_leaves_no_attempt_so_retry_works(
        self, session, sample_project, monkeypatch
    ):
        import learning_ext.quiz.service as svc

        calls = {"n": 0}

        def _flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("上游超时")
            return {
                "score": 1.0,
                "missed_points": [],
                "error_type": "incomplete",
                "feedback": "很好",
            }

        monkeypatch.setattr(svc, "chat_json", _flaky)
        quiz = _make_quiz(session, sample_project.id)
        q = _make_question(session, quiz, qtype="short", answer="要点")
        rid = "req-retry"

        with pytest.raises(RuntimeError):
            grade_answer(session, q.id, "答案", "default", request_id=rid)
        assert session.exec(select(QuizAttempt)).all() == []

        # 同一个 request_id 重试: 上次没落库, 这次应当成功
        attempt = grade_answer(session, q.id, "答案", "default", request_id=rid)
        assert attempt.is_correct is True


class TestQuizSummaryAndRetry:
    def _quiz_with_two_questions(self, session, project_id):
        quiz = _make_quiz(session, project_id)
        q_ok = _make_question(session, quiz)
        q_bad = _make_question(session, quiz)
        grade_answer(session, q_ok.id, "A", "default", request_id="r1")
        grade_answer(session, q_bad.id, "D", "default", request_id="r2")
        return quiz, q_ok, q_bad

    def test_summary_counts(self, session, sample_project):
        quiz, _, _ = self._quiz_with_two_questions(session, sample_project.id)
        summary = get_quiz_summary(session, quiz.id, "default")
        assert summary["total"] == 2
        assert summary["answered"] == 2
        assert summary["correct"] == 1
        assert summary["wrong_count"] == 1
        assert summary["accuracy"] == pytest.approx(0.5)

    def test_summary_marks_unanswered(self, session, sample_project):
        quiz = _make_quiz(session, sample_project.id)
        _make_question(session, quiz)
        summary = get_quiz_summary(session, quiz.id, "default")
        assert summary["answered"] == 0
        assert summary["rows"][0]["answered"] is False

    def test_retry_quiz_copies_only_wrong_questions(self, session, sample_project):
        quiz, q_ok, q_bad = self._quiz_with_two_questions(session, sample_project.id)
        retry = create_retry_quiz(session, quiz.id, "default")
        assert retry is not None
        copied = session.exec(
            select(QuizQuestion).where(QuizQuestion.quiz_id == retry.id)
        ).all()
        assert [c.stem for c in copied] == [q_bad.stem]

    def test_retry_quiz_returns_none_without_wrong_answers(self, session, sample_project):
        quiz = _make_quiz(session, sample_project.id)
        q = _make_question(session, quiz)
        grade_answer(session, q.id, "A", "default", request_id="r")
        assert create_retry_quiz(session, quiz.id, "default") is None

    def test_retry_quiz_nonexistent_raises(self, session):
        with pytest.raises(ValueError, match="不存在"):
            create_retry_quiz(session, 99999, "default")


class TestGetWeakNodes:
    def test_returns_low_mastery_nodes(self, session, sample_project):
        # 把一个节点 mastery 设低
        node = session.exec(select(KnowledgeNode)).first()
        node.mastery = 0.1
        session.add(node)
        session.commit()
        weak = get_weak_nodes(session, sample_project.id, threshold=0.5)
        assert any(n.id == node.id for n in weak)

    def test_excludes_mastered(self, session, sample_project):
        node = session.exec(select(KnowledgeNode)).first()
        node.mastery = 0.1
        node.status = "mastered"
        session.add(node)
        session.commit()
        weak = get_weak_nodes(session, sample_project.id, threshold=0.5)
        assert not any(n.id == node.id for n in weak)

    def test_ordered_by_mastery_asc(self, session, sample_project):
        nodes = session.exec(select(KnowledgeNode)).all()
        nodes[0].mastery = 0.5
        nodes[1].mastery = 0.1
        nodes[2].mastery = 0.3
        session.add_all(nodes)
        session.commit()
        weak = get_weak_nodes(session, sample_project.id, threshold=0.6)
        masteries = [n.mastery for n in weak]
        assert masteries == sorted(masteries)


class TestSelectScopeNodes:
    def test_unknown_scope_raises(self, session, sample_project):
        with pytest.raises(ValueError, match="scope"):
            select_scope_nodes(session, sample_project.id, "whatever")

    def test_learned_excludes_pending(self, session, sample_project):
        nodes = session.exec(select(KnowledgeNode)).all()
        for n in nodes:
            n.status = "learning"
        nodes[0].status = "pending"
        session.add_all(nodes)
        session.commit()
        learned = select_scope_nodes(session, sample_project.id, "learned")
        assert nodes[0].id not in {n.id for n in learned}

    def test_empty_project_returns_empty(self, session):
        assert select_scope_nodes(session, 99999, "weak") == []
