"""查漏补缺测验页面。

流程：选范围 → 生成测验 → 逐题作答 → 提交后即时反馈 → 成绩汇总 → 错题重测。

关键约束：
    - 每道题在「展示」时生成一个 request_id，一次展示只落一条作答记录，
      网络重试或双击不会重复计分、不会重复回写掌握度。
    - LLM 失败/返回不合规时，题目不会被消耗，重新点「提交答案」即可重试。
"""

from __future__ import annotations

import json
import logging
import uuid

import gradio as gr
from ktem.app import BasePage
from ktem.db.engine import engine
from sqlmodel import Session, select

from learning_ext.db.models import LearningProject, QuizQuestion
from learning_ext.quiz import (
    ERROR_LABEL,
    QTYPE_LABEL,
    create_retry_quiz,
    generate_quiz,
    get_quiz_summary,
    grade_answer,
    select_scope_nodes,
)

logger = logging.getLogger(__name__)

SCOPE_CHOICES = [
    ("薄弱知识点优先", "weak"),
    ("已学过的知识点", "learned"),
    ("项目全部知识点", "all"),
]

NO_PROJECT_MD = "*还没有学习项目。请先到「🎯 学习路线」生成并保存路线。*"


class QuizPage(BasePage):
    """查漏补缺测验页面。"""

    def __init__(self, app):
        super().__init__(app)
        # {"quiz_id": int, "question_ids": [...], "index": int, "request_id": str}
        self.quiz_state = gr.State(None)

    # ==================== UI ====================

    def on_building_ui(self):
        gr.Markdown("# 📝 查漏补缺测验")
        gr.Markdown(
            "AI 根据你的**薄弱知识点**自动出题，逐题作答、即时批改。"
            "答完可一键重测错题，成绩会回写到掌握度。"
        )

        gr.Markdown("---\n### 🎯 出题范围")
        with gr.Row():
            self.project_id = gr.Dropdown(
                label="学习项目", choices=[], value=None, scale=3, interactive=True
            )
            self.scope = gr.Dropdown(
                label="范围",
                choices=SCOPE_CHOICES,
                value="weak",
                scale=2,
                interactive=True,
            )
            self.count = gr.Slider(
                label="题目数量", minimum=1, maximum=20, value=5, step=1, scale=2
            )
            self.qtype = gr.Dropdown(
                label="题型",
                choices=[
                    ("混合出题", "mixed"),
                    ("选择题", "choice"),
                    ("填空题", "fill"),
                    ("简答题", "short"),
                    ("实操题", "practice"),
                ],
                value="mixed",
                scale=2,
            )
        with gr.Row():
            self.btn_gen = gr.Button("🎯 生成测验", variant="primary")
            self.btn_refresh = gr.Button("🔄 刷新项目", size="sm")

        self.quiz_status = gr.Markdown("")

        with gr.Group(visible=False) as self.answer_group:
            gr.Markdown("---")
            self.progress_md = gr.Markdown("")
            self.stem_md = gr.Markdown("")
            self.options_radio = gr.Radio(label="选择答案", choices=[], visible=False)
            self.answer_box = gr.Textbox(
                label="你的答案",
                lines=3,
                placeholder="写下你的答案，简答题按要点给分",
                visible=False,
            )
            with gr.Row():
                self.btn_submit = gr.Button("✅ 提交答案", variant="primary")
                self.btn_next = gr.Button("⏭ 下一题")
            self.feedback_md = gr.Markdown("")

        gr.Markdown("---\n### 📊 本次成绩")
        self.summary_md = gr.Markdown("*还没有进行中的测验。*")
        self.btn_retry = gr.Button("🔁 错题重测", visible=False)

    # ==================== 事件 ====================

    def on_register_events(self):
        self._app.app.load(fn=self._refresh_projects, outputs=[self.project_id])
        self.btn_refresh.click(fn=self._refresh_projects, outputs=[self.project_id])

        quiz_outputs = [
            self.quiz_state,
            self.answer_group,
            self.progress_md,
            self.stem_md,
            self.options_radio,
            self.answer_box,
            self.feedback_md,
            self.quiz_status,
        ]
        self.btn_gen.click(
            fn=self._generate,
            inputs=[self.project_id, self.scope, self.count, self.qtype],
            outputs=quiz_outputs + [self.summary_md, self.btn_retry],
        )
        self.btn_submit.click(
            fn=self._submit,
            inputs=[self.quiz_state, self.options_radio, self.answer_box],
            outputs=[self.quiz_state, self.feedback_md, self.quiz_status],
        )
        self.btn_next.click(
            fn=self._next_question,
            inputs=[self.quiz_state],
            outputs=quiz_outputs + [self.summary_md, self.btn_retry],
        )
        self.btn_retry.click(
            fn=self._retry,
            inputs=[self.quiz_state],
            outputs=quiz_outputs + [self.summary_md, self.btn_retry],
        )

    # ==================== 项目 ====================

    def _refresh_projects(self):
        try:
            with Session(engine) as session:
                projects = session.exec(
                    select(LearningProject).order_by(LearningProject.id.desc())
                ).all()
                if not projects:
                    return gr.update(choices=[], value=None)
                return gr.update(
                    choices=[(f"#{p.id} {p.title[:30]}", str(p.id)) for p in projects],
                    value=str(projects[0].id),
                )
        except Exception:
            logger.exception("刷新项目失败")
            return gr.update()

    # ==================== 出题 ====================

    def _generate(self, project_id, scope, count, qtype):
        if not project_id:
            return self._result("⚠️ 请先选择学习项目")

        try:
            pid = int(project_id)
        except (ValueError, TypeError):
            return self._result("⚠️ 项目 ID 无效")

        try:
            with Session(engine) as session:
                nodes = select_scope_nodes(session, pid, scope or "weak")
                if not nodes:
                    return self._result(
                        "⚠️ 该范围内没有可出题的知识点。"
                        "换个范围试试，或先到「🎯 学习路线」补充知识点。"
                    )
                node_ids = [n.id for n in nodes]
                quiz = generate_quiz(
                    session,
                    "default",
                    node_ids,
                    project_id=pid,
                    count=int(count),
                    qtype=qtype or "mixed",
                )
                questions = list(
                    session.exec(
                        select(QuizQuestion)
                        .where(QuizQuestion.quiz_id == quiz.id)
                        .order_by(QuizQuestion.id)
                    ).all()
                )
                question_ids = [q.id for q in questions]
        except Exception as e:
            logger.exception("生成测验失败")
            return self._result(f"❌ 生成失败：{e}")

        state = {
            "quiz_id": quiz.id,
            "question_ids": question_ids,
            "index": 0,
            "request_id": None,
        }
        note = f"📋 从 {len(node_ids)} 个知识点出题，共 {len(question_ids)} 题"
        return self._render_question(state, note) + [
            "*答完所有题目后这里会显示成绩汇总。*",
            gr.update(visible=False),
        ]

    # ==================== 答题 ====================

    def _submit(self, state, choice_value, text_value):
        if not state:
            return state, "", "⚠️ 请先生成测验"

        with Session(engine) as session:
            q = self._current_question(session, state)
            if q is None:
                return state, "", "⚠️ 题目不存在，请重新生成测验"

            answer = choice_value if q.qtype == "choice" else text_value
            request_id = state.get("request_id")
            if not request_id:
                # 题目没有有效的展示 ID（例如状态被外部重置），补一个
                request_id = self._new_request_id(state, q.id)
                state = {**state, "request_id": request_id}

            try:
                attempt = grade_answer(
                    session,
                    q.id,
                    answer or "",
                    "default",
                    request_id=request_id,
                )
            except Exception as e:
                logger.exception("批改失败")
                return state, f"❌ 批改失败：{e}\n\n*可以直接重试提交，本题不会被重复计分。*", "⚠️ 批改失败"

        mark = "✅ 答对" if attempt.is_correct else "❌ 答错"
        extra = ""
        if not attempt.is_correct and attempt.error_type:
            extra = f"\n\n**错误类型**：{ERROR_LABEL.get(attempt.error_type, attempt.error_type)}"
        feedback = (
            f"### {mark}（得分 {attempt.score:.0%}）{extra}\n\n{attempt.feedback}"
        )
        return state, feedback, "点击「⏭ 下一题」继续"

    def _next_question(self, state):
        if not state:
            return self._result("⚠️ 请先生成测验")

        index = int(state.get("index", 0)) + 1
        if index >= len(state.get("question_ids") or []):
            return self._finish(state)

        new_state = {**state, "index": index, "request_id": None}
        return self._render_question(new_state) + [
            gr.update(),
            gr.update(),
        ]

    def _finish(self, state):
        quiz_id = state.get("quiz_id")
        with Session(engine) as session:
            summary = get_quiz_summary(session, quiz_id, "default")
        md = self._render_summary(summary, finished=True)
        result = [
            state,
            gr.update(visible=True),
            gr.update(value=f"*本次测验已完成：{summary['answered']}/{summary['total']} 题已答*"),
            gr.update(value="### 🎉 测验完成"),
            gr.update(visible=False, value=None, choices=[]),
            gr.update(visible=False, value=""),
            gr.update(value=""),
            gr.update(value="✅ 已完成，可查看成绩或重测错题"),
        ]
        return result + [gr.update(value=md), gr.update(visible=summary["wrong_count"] > 0)]

    def _retry(self, state):
        if not state:
            return self._result("⚠️ 请先生成测验")

        with Session(engine) as session:
            try:
                retry = create_retry_quiz(session, state["quiz_id"], "default")
            except Exception as e:
                logger.exception("生成错题重测失败")
                return self._result(f"❌ 重测生成失败：{e}")
            if retry is None:
                return self._result("🎉 没有错题，不需要重测")
            question_ids = [
                q.id
                for q in session.exec(
                    select(QuizQuestion)
                    .where(QuizQuestion.quiz_id == retry.id)
                    .order_by(QuizQuestion.id)
                ).all()
            ]

        new_state = {
            "quiz_id": retry.id,
            "question_ids": question_ids,
            "index": 0,
            "request_id": None,
        }
        note = f"🔁 已生成错题重测：共 {len(question_ids)} 题"
        return self._render_question(new_state, note) + [
            gr.update(value=f"*重测测验 #{retry.id}，共 {len(question_ids)} 题错题。*"),
            gr.update(visible=False),
        ]

    # ==================== 渲染 ====================

    def _new_request_id(self, state, question_id) -> str:
        return f"quiz{state.get('quiz_id')}-q{question_id}-{uuid.uuid4().hex}"

    def _current_question(self, session: Session, state):
        ids = state.get("question_ids") or []
        index = int(state.get("index", 0))
        if not 0 <= index < len(ids):
            return None
        return session.get(QuizQuestion, ids[index])

    def _load_options(self, raw: str) -> list[str]:
        try:
            data = json.loads(raw or "[]")
        except (json.JSONDecodeError, TypeError):
            return []
        return [str(x) for x in data] if isinstance(data, list) else []

    def _empty_result(self):
        """清空答题区。顺序与 quiz_outputs 一致。"""
        return [
            None,
            gr.update(visible=False),
            gr.update(value=""),
            gr.update(value=""),
            gr.update(visible=False, choices=[], value=None),
            gr.update(visible=False, value=""),
            gr.update(value=""),
            gr.update(value=""),
        ]

    @staticmethod
    def _with_status(result, status):
        result = list(result)
        result[7] = gr.update(value=status)
        return result

    def _result(self, status: str):
        """清空答题区并给出状态。共 10 项, 与 quiz_outputs + [汇总, 重测按钮] 对齐。"""
        return self._with_status(self._empty_result(), status) + [
            gr.update(),
            gr.update(visible=False),
        ]

    def _render_question(self, state, status: str = ""):
        """渲染当前题目。顺序与 quiz_outputs 一致 (末尾两项由调用方附加)。"""
        with Session(engine) as session:
            q = self._current_question(session, state)
            if q is None:
                return self._with_status(self._empty_result(), "⚠️ 题目不存在")

            options = self._load_options(q.options)
            is_choice = q.qtype == "choice"
            total = len(state.get("question_ids") or [])
            index = int(state.get("index", 0))

            if not state.get("request_id"):
                state = {
                    **state,
                    "request_id": self._new_request_id(state, q.id),
                }

            progress = (
                f"**第 {index + 1} / {total} 题** · "
                f"{QTYPE_LABEL.get(q.qtype, q.qtype)} · 难度 {q.difficulty}"
            )
            stem = f"### {q.stem}"

        return [
            state,
            gr.update(visible=True),
            gr.update(value=progress),
            gr.update(value=stem),
            gr.update(visible=is_choice, choices=options, value=None),
            gr.update(visible=not is_choice, value=""),
            gr.update(value=""),
            gr.update(value=status or ("*选择答案后点「提交答案」*" if is_choice else "*写下答案后点「提交答案」*")),
        ]

    def _render_summary(self, summary: dict, *, finished: bool) -> str:
        if summary["total"] == 0:
            return "*本次测验没有题目。*"

        head = (
            f"**共 {summary['total']} 题** · 已答 {summary['answered']} · "
            f"答对 {summary['correct']} · 正确率 {summary['accuracy']:.0%} · "
            f"平均得分 {summary['avg_score']:.0%}"
        )
        lines = [head, ""]
        for i, row in enumerate(summary["rows"], 1):
            if not row["answered"]:
                lines.append(f"{i}. ⬜ *未作答* — {row['stem'][:60]}")
                continue
            icon = "✅" if row["is_correct"] else "❌"
            detail = f"（得分 {row['score']:.0%}）"
            if not row["is_correct"] and row["error_type"]:
                detail += f" · {ERROR_LABEL.get(row['error_type'], row['error_type'])}"
            lines.append(f"{i}. {icon} {detail} — {row['stem'][:60]}")

        if summary["wrong_count"]:
            lines.append("")
            lines.append(f"> 有 {summary['wrong_count']} 道错题，点下方「🔁 错题重测」再练一遍。")
        elif finished and summary["answered"] == summary["total"]:
            lines.append("")
            lines.append("> 🎉 全部答对，这组知识点可以进入下一阶段了。")
        return "\n".join(lines)
