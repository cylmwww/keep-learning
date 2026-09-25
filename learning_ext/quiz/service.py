"""查漏补缺测验引擎。

流程：
    1. 选范围 (薄弱知识点优先)
    2. AI 出题 → 严格类型校验 → 入库 (不合规的单题丢弃并记日志)
    3. 逐题作答 → 选择题确定性比较 / 主观题按要点给分 → 单一事务回写掌握度
    4. 错题重测

批改契约：
    - ``is_correct`` 不再采信模型输出，由 ``score`` 和题型阈值算出；
      模型只提供 ``score`` / ``error_type`` / ``missed_points`` / ``feedback``。
    - ``request_id`` 由调用方在「展示题目」时生成，一次展示只能落一条作答；
      网络重试或双击命中唯一索引，不会重复计分，也不会重复回写掌握度。
"""

from __future__ import annotations

import json
import logging
import re
from typing import List, Optional, Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlmodel import select

from learning_ext.db.models import KnowledgeNode, Quiz, QuizAttempt, QuizQuestion
from learning_ext.llm import LLMOutputError, chat_json
from learning_ext.llm.validate import (
    as_str,
    require_dict,
    require_enum,
    require_int,
    require_list,
    require_number,
    require_str,
    require_str_list,
)
from learning_ext.progress.service import update_mastery

logger = logging.getLogger(__name__)

QTYPES = ("choice", "fill", "short", "practice")
QUIZ_TYPES = QTYPES + ("mixed",)
SCOPES = ("weak", "learned", "all")

# 各题型「算答对」的最低得分。主观题允许部分得分, 但必须覆盖足够要点。
PASS_THRESHOLD = {
    "choice": 1.0,
    "fill": 0.8,
    "short": 0.7,
    "practice": 0.6,
}

ERROR_TYPES = (
    "concept_unclear",  # 概念理解错误
    "detail_missed",  # 细节遗漏/记错
    "incomplete",  # 要点不全
    "procedural_error",  # 步骤/顺序错误
    "blank",  # 未作答
)
ERROR_LABEL = {
    "concept_unclear": "概念不清",
    "detail_missed": "细节遗漏",
    "incomplete": "要点不全",
    "procedural_error": "步骤错误",
    "blank": "未作答",
}
QTYPE_LABEL = {
    "choice": "选择题",
    "fill": "填空题",
    "short": "简答题",
    "practice": "实操题",
}

SYSTEM = """你是一位严谨的命题专家。根据知识点信息出测验题。
返回 JSON 数组，每题格式：
{
  "node_code": "该题考的知识点编号，必须是给定知识点列表里的编号",
  "qtype": "choice|fill|short|practice",
  "stem": "题干",
  "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
  "answer": "标准答案",
  "explanation": "解析说明",
  "difficulty": 1到5的整数
}
规则：
- node_code 必须原样取自给定列表，不要自己编号
- choice：必须有 4 个选项，answer 只填选项字母（如 "B"），不要填选项内容
- fill：options 传空数组 []，answer 填标准答案
- short：options 传空数组 []，answer 填分点式参考答案，要点之间用 "；" 分隔
- practice：options 传空数组 []，answer 填参考操作步骤
- difficulty 必须是整数，不要加引号
- 只返回 JSON 数组，不要额外说明"""

GRADE_SYSTEM = """你是阅卷老师，按评分要点给分。
返回 JSON：
{
  "score": 0.0 到 1.0 之间的数字,
  "missed_points": ["未覆盖的要点"],
  "error_type": "concept_unclear|detail_missed|incomplete|procedural_error|blank",
  "feedback": "点评（指出对错原因，2-3 句）"
}
规则：
- 完全正确给 1.0；完全错误或未作答给 0.0；部分正确按要点覆盖比例给 0.1-0.9
- 未作答时 error_type 填 "blank"
- 答错但方向正确、只是漏要点时 error_type 填 "incomplete"
- 概念理解反了填 "concept_unclear"；细节记错填 "detail_missed"；步骤/顺序错填 "procedural_error"
- score 必须是数字（不要加引号），error_type 必须是上面列出的取值之一
- 只返回 JSON，不要额外说明"""


# ==================== 题目解析 (严格校验) ====================


def _normalize_text(text: str) -> str:
    """归一化文本用于选项比对：去空白、去标点、转小写。"""
    return re.sub(r"[\s　.,，。:：;；!！?？\"'“”‘’()（）\[\]【】]+", "", text).lower()


def _load_options(raw: str) -> List[str]:
    """QuizQuestion.options 存的 JSON 数组；解析失败按空列表处理。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("题目选项不是合法 JSON，按无选项处理")
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data]


def _option_bodies(options: Sequence[str]) -> List[str]:
    """剥掉选项的 "A." 前缀，返回归一化后的选项正文。"""
    bodies = []
    for opt in options:
        text = (opt or "").strip()
        head, sep, rest = text.partition(".")
        if sep and len(head.strip()) == 1 and head.strip().isalpha():
            text = rest.strip()
        bodies.append(_normalize_text(text))
    return bodies


def _answer_letter(value: str, options: Sequence[str]) -> Optional[str]:
    """把标准答案归一化成选项字母。支持 "B"、"B." 和选项正文。"""
    text = (value or "").strip()
    if not text:
        return None
    head = text.split(".")[0].strip().upper()
    if len(head) == 1 and "A" <= head <= "Z" and ord(head) - 65 < len(options):
        return head
    body = _normalize_text(text)
    if body:
        for i, opt_body in enumerate(_option_bodies(options)):
            if opt_body and opt_body == body:
                return chr(65 + i)
    return None


def _user_letter(value: str, options: Sequence[str]) -> Optional[str]:
    """把学习者作答归一化成选项字母。界面上选中的是完整选项文本。"""
    text = (value or "").strip()
    if not text:
        return None
    head = text.split(".")[0].strip().upper()
    if len(head) == 1 and "A" <= head <= "Z" and ord(head) - 65 < len(options):
        return head
    body = _normalize_text(text)
    if body:
        for i, opt_body in enumerate(_option_bodies(options)):
            if opt_body and opt_body == body:
                return chr(65 + i)
    return None


def _parse_question(raw: dict, index: int, node_by_code: dict) -> dict:
    """校验单道题的 LLM 输出。任何类型不符都抛 LLMOutputError。"""
    field = f"questions[{index}]"
    item = require_dict(raw, field)

    qtype = require_enum(item.get("qtype"), f"{field}.qtype", QTYPES)
    stem = require_str(item.get("stem"), f"{field}.stem", max_len=4000)
    answer_raw = require_str(item.get("answer"), f"{field}.answer", max_len=4000)
    explanation = as_str(item.get("explanation"), f"{field}.explanation", max_len=4000)
    difficulty = require_int(
        item.get("difficulty", 3), f"{field}.difficulty", min_value=1, max_value=5
    )

    node_id: Optional[int] = None
    raw_code = item.get("node_code")
    if raw_code is not None:
        code = require_str(raw_code, f"{field}.node_code")
        node_id = node_by_code.get(code)
        if node_id is None:
            raise LLMOutputError(f"{field}.node_code 不在出题范围内")
    elif len(node_by_code) == 1:
        node_id = next(iter(node_by_code.values()))
    else:
        raise LLMOutputError(f"{field}.node_code 缺失，无法确定知识点")

    options: List[str] = []
    if qtype == "choice":
        options = require_str_list(
            item.get("options"), f"{field}.options", min_items=2, max_items=6
        )
        answer = _answer_letter(answer_raw, options)
        if answer is None:
            raise LLMOutputError(
                f"字段 `{field}.answer` 不是有效选项字母或选项正文：{answer_raw!r}"
            )
    else:
        # 非选择题不持有选项；模型多填了也不影响作答, 直接忽略
        answer = answer_raw

    return {
        "node_id": node_id,
        "qtype": qtype,
        "stem": stem,
        "options": options,
        "answer": answer,
        "explanation": explanation,
        "difficulty": difficulty,
    }


# ==================== 出题 ====================


def select_scope_nodes(
    session: Session,
    project_id: int,
    scope: str = "weak",
    *,
    limit: int = 20,
    threshold: float = 0.5,
) -> List[KnowledgeNode]:
    """按范围取本次出题的知识点。"""
    if scope not in SCOPES:
        raise ValueError(f"scope 必须为 {SCOPES}，收到 {scope!r}")

    stmt = select(KnowledgeNode).where(KnowledgeNode.project_id == project_id)
    if scope == "weak":
        stmt = (
            stmt.where(KnowledgeNode.status != "mastered")
            .where(KnowledgeNode.mastery < threshold)
            .order_by(KnowledgeNode.mastery.asc())
        )
    elif scope == "learned":
        stmt = stmt.where(
            KnowledgeNode.status.in_(("learning", "reviewing", "weak", "mastered"))
        )
    stmt = stmt.limit(limit)
    return list(session.exec(stmt).all())


def generate_quiz(
    session: Session,
    user_id: str,
    node_ids: List[int],
    *,
    project_id: Optional[int] = None,
    count: int = 5,
    qtype: str = "mixed",
    model_name: Optional[str] = None,
) -> Quiz:
    """AI 出题生成测验。

    Args:
        node_ids: 出题范围的知识点 id
        count: 题目数量 (1-50)
        qtype: choice|fill|short|practice|mixed

    Raises:
        ValueError: 范围为空或参数非法
        LLMOutputError: 模型返回的题目全部不合规
    """
    if qtype not in QUIZ_TYPES:
        raise ValueError(f"qtype 必须为 {QUIZ_TYPES}，收到 {qtype!r}")
    if not 1 <= count <= 50:
        raise ValueError(f"count 必须在 1-50 之间，收到 {count}")

    nodes = session.exec(select(KnowledgeNode).where(KnowledgeNode.id.in_(node_ids))).all()
    if not nodes:
        raise ValueError("未找到指定知识点")

    nodes_text = "\n".join(
        f"- [{n.code}] {n.title} (难度{n.difficulty}): {n.description}" for n in nodes
    )
    prompt = f"""请为以下知识点出 {count} 道测验题。
题型偏好：{qtype}

【知识点】
{nodes_text}

每题都要带 node_code，取值为上面方括号里的编号。
返回 {count} 题的 JSON 数组。"""

    result = chat_json(prompt, system=SYSTEM, model_name=model_name)

    if isinstance(result, list):
        raw_items = result
    elif isinstance(result, dict) and "questions" in result:
        raw_items = require_list(result.get("questions"), "questions")
    else:
        raise LLMOutputError(
            f"出题结果应为 JSON 数组，实际为 {type(result).__name__}"
        )

    node_by_code = {n.code: n.id for n in nodes}

    parsed: List[dict] = []
    dropped = 0
    for i, item in enumerate(raw_items[:count]):
        try:
            parsed.append(_parse_question(item, i, node_by_code))
        except LLMOutputError as e:
            dropped += 1
            logger.warning("丢弃第 %s 道不合规的题目: %s", i + 1, e)

    if not parsed:
        raise LLMOutputError(
            f"AI 返回的 {len(raw_items)} 道题全部格式不合规，请重试或更换模型"
        )

    quiz = Quiz(
        project_id=project_id,
        user_id=user_id,
        quiz_type=qtype,
        scope_node_ids=",".join(str(i) for i in node_ids),
        title=f"测验 ({len(parsed)}题)",
    )
    session.add(quiz)
    session.flush()

    for q in parsed:
        session.add(
            QuizQuestion(
                quiz_id=quiz.id,
                node_id=q["node_id"],
                qtype=q["qtype"],
                stem=q["stem"],
                options=json.dumps(q["options"], ensure_ascii=False),
                answer=q["answer"],
                explanation=q["explanation"],
                difficulty=q["difficulty"],
            )
        )

    session.commit()
    if dropped:
        logger.info("本次出题丢弃 %s 道不合规题目", dropped)
    session.refresh(quiz)
    return quiz


# ==================== 批改 ====================


def _verdict(
    score: float,
    is_correct: bool,
    error_type: str,
    feedback: str,
) -> dict:
    return {
        "score": max(0.0, min(1.0, float(score))),
        "is_correct": bool(is_correct),
        "error_type": error_type,
        "feedback": feedback,
    }


def _grade_choice(q: QuizQuestion, answer_text: str) -> Optional[dict]:
    """选择题确定性比较：不发 LLM 请求。

    选项数据异常（标准答案不是字母、选项缺失）时返回 None，由调用方回退语义批改。
    """
    options = _load_options(q.options)
    if not answer_text:
        return _verdict(0.0, False, "blank", f"未作答。正确答案：{q.answer}")
    correct = _answer_letter(q.answer, options)
    if correct is None or not options:
        return None
    picked = _user_letter(answer_text, options)
    if picked is None:
        return _verdict(
            0.0,
            False,
            "concept_unclear",
            f"无法识别作答「{answer_text}」。正确答案：{q.answer}",
        )
    if picked == correct:
        detail = q.explanation or f"正确答案：{q.answer}"
        return _verdict(1.0, True, "", f"✅ 正确。{detail}")
    return _verdict(
        0.0,
        False,
        "concept_unclear",
        f"❌ 选错。正确答案：{q.answer}" + (f"\n\n{q.explanation}" if q.explanation else ""),
    )


def _grade_open(q: QuizQuestion, answer_text: str, *, model_name: Optional[str] = None) -> dict:
    """主观题按要点给分。LLM 只给 score，is_correct 由阈值算出。"""
    if not answer_text:
        return _verdict(
            0.0, False, "blank", f"未作答。参考答案：\n\n{q.answer}"
        )

    prompt = f"""【题型】{q.qtype}
【题目】{q.stem}
【参考答案】{q.answer}
【学习者答案】{answer_text}

请按评分要点给分。"""
    result = require_dict(
        chat_json(prompt, system=GRADE_SYSTEM, model_name=model_name), "grade_result"
    )

    score = require_number(
        result.get("score"), "grade_result.score", min_value=0.0, max_value=1.0
    )
    error_type = require_enum(
        result.get("error_type"), "grade_result.error_type", ERROR_TYPES
    )
    feedback = require_str(result.get("feedback"), "grade_result.feedback", max_len=2000)
    missed = require_str_list(
        result.get("missed_points") or [], "grade_result.missed_points"
    )

    threshold = PASS_THRESHOLD.get(q.qtype, 0.7)
    is_correct = score >= threshold
    if is_correct:
        error_type = ""

    parts = [feedback]
    if missed:
        parts.append("未覆盖要点：" + "；".join(missed))
    if not is_correct:
        parts.append(f"参考答案：\n\n{q.answer}")
    return _verdict(score, is_correct, error_type, "\n\n".join(parts))


def find_attempt_by_request(session: Session, request_id: str) -> Optional[QuizAttempt]:
    return session.exec(
        select(QuizAttempt).where(QuizAttempt.request_id == request_id)
    ).first()


def grade_answer(
    session: Session,
    question_id: int,
    user_answer: str,
    user_id: str = "default",
    *,
    request_id: Optional[str] = None,
    model_name: Optional[str] = None,
) -> QuizAttempt:
    """批改单题答案，并在同一事务内回写掌握度。

    Args:
        request_id: 本次「展示→提交」的唯一 ID。重复提交直接返回已有记录，
            不会新建 attempt、不会重复回写掌握度。
    """
    if request_id:
        existing = find_attempt_by_request(session, request_id)
        if existing is not None:
            if existing.question_id != question_id or existing.user_id != user_id:
                raise ValueError(f"request_id `{request_id}` 已被其他作答占用")
            return existing

    q = session.get(QuizQuestion, question_id)
    if q is None:
        raise ValueError(f"Question {question_id} not found")

    answer_text = (user_answer or "").strip()

    # LLM 请求放在数据库事务之外
    if q.qtype == "choice":
        verdict = _grade_choice(q, answer_text)
        if verdict is None:
            logger.warning("题目 %s 选项数据异常，回退到语义批改", question_id)
            verdict = _grade_open(q, answer_text, model_name=model_name)
    else:
        verdict = _grade_open(q, answer_text, model_name=model_name)

    attempt = QuizAttempt(
        question_id=question_id,
        user_id=user_id,
        user_answer=answer_text,
        is_correct=verdict["is_correct"],
        score=verdict["score"],
        error_type=verdict["error_type"],
        feedback=verdict["feedback"],
        request_id=request_id,
    )

    # 单一事务边界：作答记录 + 掌握度回写同时生效
    session.add(attempt)
    try:
        session.flush()
        if q.node_id:
            update_mastery(session, q.node_id, correct=verdict["is_correct"], commit=False)
        session.commit()
    except IntegrityError:
        # 并发/双击落到唯一索引上：回滚后返回已存在的那条
        session.rollback()
        if request_id:
            existing = find_attempt_by_request(session, request_id)
            if existing is not None:
                return existing
        raise
    session.refresh(attempt)
    return attempt


# ==================== 结果与重测 ====================


def latest_attempt(
    session: Session, question_id: int, user_id: str = "default"
) -> Optional[QuizAttempt]:
    """某题该用户最近一次作答。"""
    return session.exec(
        select(QuizAttempt)
        .where(QuizAttempt.question_id == question_id)
        .where(QuizAttempt.user_id == user_id)
        .order_by(QuizAttempt.attempted_at.desc(), QuizAttempt.id.desc())
    ).first()


def get_quiz_summary(session: Session, quiz_id: int, user_id: str = "default") -> dict:
    """汇总一次测验的作答情况，用于成绩面板与错题重测。"""
    questions = list(
        session.exec(
            select(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id).order_by(QuizQuestion.id)
        ).all()
    )
    rows = []
    for q in questions:
        a = latest_attempt(session, q.id, user_id)
        rows.append(
            {
                "question_id": q.id,
                "qtype": q.qtype,
                "stem": q.stem,
                "answer": q.answer,
                "explanation": q.explanation,
                "answered": a is not None,
                "is_correct": None if a is None else bool(a.is_correct),
                "score": 0.0 if a is None else float(a.score or 0.0),
                "error_type": "" if a is None else (a.error_type or ""),
                "user_answer": "" if a is None else a.user_answer,
                "feedback": "" if a is None else a.feedback,
            }
        )
    answered = [r for r in rows if r["answered"]]
    correct = [r for r in answered if r["is_correct"]]
    return {
        "quiz_id": quiz_id,
        "total": len(rows),
        "answered": len(answered),
        "correct": len(correct),
        "wrong_count": len(answered) - len(correct),
        "accuracy": (len(correct) / len(answered)) if answered else 0.0,
        "avg_score": (
            sum(r["score"] for r in answered) / len(answered) if answered else 0.0
        ),
        "rows": rows,
    }


def create_retry_quiz(
    session: Session, quiz_id: int, user_id: str = "default"
) -> Optional[Quiz]:
    """把最近一次答错的题目复制成一份新的重测测验。

    复制而非复用原题，使重测的作答记录独立于首次作答。
    没有错题时返回 None。
    """
    quiz = session.get(Quiz, quiz_id)
    if quiz is None:
        raise ValueError(f"Quiz {quiz_id} 不存在")

    summary = get_quiz_summary(session, quiz_id, user_id)
    wrong_rows = [r for r in summary["rows"] if r["answered"] and not r["is_correct"]]
    if not wrong_rows:
        return None

    wrong_ids = [r["question_id"] for r in wrong_rows]
    questions = session.exec(
        select(QuizQuestion).where(QuizQuestion.id.in_(wrong_ids))
    ).all()
    by_id = {q.id: q for q in questions}

    retry = Quiz(
        project_id=quiz.project_id,
        user_id=user_id,
        quiz_type=quiz.quiz_type,
        scope_node_ids=quiz.scope_node_ids,
        title=f"错题重测 (来自 #{quiz_id}，{len(wrong_rows)}题)",
    )
    session.add(retry)
    session.flush()

    for qid in wrong_ids:  # 保持原测验的题目顺序
        src = by_id.get(qid)
        if src is None:
            continue
        session.add(
            QuizQuestion(
                quiz_id=retry.id,
                node_id=src.node_id,
                qtype=src.qtype,
                stem=src.stem,
                options=src.options,
                answer=src.answer,
                explanation=src.explanation,
                difficulty=src.difficulty,
            )
        )
    session.commit()
    session.refresh(retry)
    return retry


def get_weak_nodes(
    session: Session,
    project_id: int,
    *,
    threshold: float = 0.5,
    limit: int = 10,
) -> List[KnowledgeNode]:
    """获取薄弱知识点 (掌握度低于阈值)，测验/复习优先针对这些。"""
    return select_scope_nodes(session, project_id, "weak", limit=limit, threshold=threshold)
