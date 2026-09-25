"""间隔复习页面。

四种评分走同一条流程：保存一次 → 刷新统计 → 拉下一张 → 隐藏答案。

    - 卡片在「展示」时生成一个 request_id，服务端据此去重：
      网络重试或双击不会重复调度、不会重复累计复习次数。
    - 评分动作是单个事件（generator），执行期间按钮保持提交中状态，
      不会出现「点了四个评分只前进一次」或「重复评分同一张卡」。
    - 卡片工具区接通「从知识点生成 → 预览 → 编辑」，不再只有生成函数。
"""

from __future__ import annotations

import logging
import uuid

import gradio as gr
from ktem.app import BasePage
from ktem.db.engine import engine
from sqlmodel import Session, select

from learning_ext.db.models import Card, KnowledgeNode, LearningProject
from learning_ext.fsrs_review import (
    RATING_AGAIN,
    RATING_EASY,
    RATING_GOOD,
    RATING_HARD,
    generate_cards_from_node,
    get_due_cards,
    get_review_stats,
    list_cards,
    review_card,
    update_card,
)

logger = logging.getLogger(__name__)

RATING_LABEL = {
    RATING_AGAIN: "😖 重来",
    RATING_HARD: "😰 困难",
    RATING_GOOD: "🙂 良好",
    RATING_EASY: "😄 简单",
}

NO_CARD_FRONT = "*点击下方「📥 加载下一张」开始复习*"
DONE_FRONT = "*🎉 太棒了！当前没有到期卡片，今天复习任务完成啦！*"
# 「全部项目」用哨兵值, 空字符串在 Gradio Dropdown 里语义不稳定
ALL_PROJECTS = "__all__"


class ReviewPage(BasePage):
    """FSRS 间隔重复复习页面。"""

    def __init__(self, app):
        super().__init__(app)
        self.current_card_id = gr.Number(value=None, precision=0, visible=False)
        self.current_request_id = gr.Textbox(value="", visible=False)

    # ==================== UI ====================

    def on_building_ui(self):
        with gr.Column(elem_id="le-review-layout"):
            with gr.Column(elem_id="le-review-body"):
                gr.Markdown("# 间隔复习")
                with gr.Accordion("复习说明", open=False):
                    gr.Markdown(
                        "加载下一张 → 思考问题 → 展开答案 → 评分。系统自动安排下次复习。\n\n"
                        "**重来**：想不起来 · **困难**：回忆费劲 · **良好**：正常回忆 · **简单**：轻松掌握"
                    )
                with gr.Row():
                    self.project_id = gr.Dropdown(
                        label="复习范围（项目）", choices=[("全部项目", ALL_PROJECTS)],
                        value=ALL_PROJECTS, scale=3, interactive=True,
                    )
                    self.btn_refresh = gr.Button("刷新项目", size="sm", scale=0, min_width=110)
                with gr.Row(elem_id="le-review-stats"):
                    self.stat_total = gr.Markdown("**总卡片数**：0")
                    self.stat_due = gr.Markdown("**今日待复习**：0")
                self.card_front = gr.Markdown(NO_CARD_FRONT)
                with gr.Accordion("📌 展开看答案", open=False) as self.answer_acc:
                    self.card_back = gr.Markdown("")

                with gr.Accordion("🃏 卡片工具（生成 / 预览 / 编辑）", open=False):
                    with gr.Row():
                        self.node_id = gr.Dropdown(
                            label="知识点", choices=[], value=None, scale=3, interactive=True
                        )
                        self.gen_count = gr.Slider(
                            label="生成数量", minimum=1, maximum=15, value=5, step=1, scale=2
                        )
                    self.btn_gen_cards = gr.Button("🃏 从当前知识点生成卡片", size="sm")
                    gr.Markdown("---")
                    with gr.Row():
                        self.card_pick = gr.Dropdown(
                            label="已有卡片", choices=[], value=None, scale=3, interactive=True
                        )
                        self.btn_reload_cards = gr.Button("🔄 刷新卡片", size="sm", scale=0)
                    with gr.Row():
                        self.card_front_edit = gr.Textbox(label="正面（问题）", lines=2, scale=1)
                        self.card_back_edit = gr.Textbox(label="背面（答案）", lines=3, scale=1)
                    self.btn_save_card = gr.Button("💾 保存修改", size="sm")
                    self.card_tool_status = gr.Markdown("")

            with gr.Column(elem_id="le-review-actions"):
                with gr.Row(equal_height=True):
                    self.btn_load = gr.Button("📥 加载下一张", variant="primary")
                with gr.Row(equal_height=True):
                    self.btn_again = gr.Button("😖 重来", variant="stop", interactive=False)
                    self.btn_hard = gr.Button("😰 困难", interactive=False)
                    self.btn_good = gr.Button("🙂 良好", variant="primary", interactive=False)
                    self.btn_easy = gr.Button("😄 简单", interactive=False)

                self.status = gr.Markdown("")


    # ==================== 事件 ====================

    def on_register_events(self):
        rating_outputs = [
            self.stat_total,
            self.stat_due,
            self.card_front,
            self.card_back,
            self.current_card_id,
            self.current_request_id,
            self.answer_acc,
            self.status,
        ]
        self._app.app.load(
            fn=self._refresh_projects, outputs=[self.project_id]
        )
        self.btn_refresh.click(fn=self._refresh_projects, outputs=[self.project_id])
        self.project_id.change(
            fn=self._on_project_change,
            inputs=[self.project_id],
            outputs=[self.stat_total, self.stat_due, self.node_id, self.card_pick],
        ).then(fn=self._load_review, inputs=[self.project_id], outputs=rating_outputs + [self.btn_again, self.btn_hard, self.btn_good, self.btn_easy, self.btn_load],
               concurrency_id="review", concurrency_limit=1)

        self.btn_load.click(
            fn=self._load_review,
            inputs=[self.project_id],
            outputs=rating_outputs + [self.btn_again, self.btn_hard, self.btn_good, self.btn_easy, self.btn_load],
            concurrency_id="review", concurrency_limit=1,
        )
        for button, rating in (
            (self.btn_again, RATING_AGAIN),
            (self.btn_hard, RATING_HARD),
            (self.btn_good, RATING_GOOD),
            (self.btn_easy, RATING_EASY),
        ):
            button.click(
                fn=self._rating_handler(rating),
                inputs=[self.current_card_id, self.current_request_id, self.project_id],
                outputs=rating_outputs + [self.btn_again, self.btn_hard, self.btn_good, self.btn_easy, self.btn_load],
                concurrency_id="review", concurrency_limit=1,
            )

        self.btn_gen_cards.click(
            fn=self._generate_cards,
            inputs=[self.project_id, self.node_id, self.gen_count],
            outputs=[self.card_pick, self.card_tool_status],
        )
        self.btn_reload_cards.click(
            fn=self._reload_cards,
            inputs=[self.project_id],
            outputs=[self.card_pick],
        )
        self.card_pick.change(
            fn=self._on_card_pick,
            inputs=[self.card_pick],
            outputs=[self.card_front_edit, self.card_back_edit],
        )
        self.btn_save_card.click(
            fn=self._save_card,
            inputs=[self.card_pick, self.card_front_edit, self.card_back_edit],
            outputs=[self.card_pick, self.card_tool_status],
        )

    # ==================== 项目 / 统计 ====================

    @staticmethod
    def _pid(project_id):
        if not project_id or project_id == ALL_PROJECTS:
            return None
        try:
            return int(project_id)
        except (ValueError, TypeError):
            return None

    def _refresh_projects(self):
        try:
            with Session(engine) as session:
                projects = session.exec(
                    select(LearningProject).order_by(LearningProject.id.desc())
                ).all()
            choices = [("全部项目", ALL_PROJECTS)] + [
                (f"#{p.id} {p.title[:30]}", str(p.id)) for p in projects
            ]
            return gr.update(choices=choices, value=ALL_PROJECTS)
        except Exception:
            logger.exception("刷新项目失败")
            return gr.update()

    def _on_project_change(self, project_id):
        pid = self._pid(project_id)
        with Session(engine) as session:
            stats = get_review_stats(session, "default", pid)
            nodes = []
            if pid is not None:
                nodes = list(
                    session.exec(
                        select(KnowledgeNode)
                        .where(KnowledgeNode.project_id == pid)
                        .order_by(KnowledgeNode.code)
                    ).all()
                )
        return (
            gr.update(value=f"**总卡片数**：{stats['total_cards']}"),
            gr.update(value=f"**今日待复习**：{stats['due_count']}"),
            gr.update(
                choices=[(f"[{n.code}] {n.title[:40]}", str(n.id)) for n in nodes],
                value=str(nodes[0].id) if nodes else None,
            ),
            self._card_choices(pid),
        )

    def _card_choices(self, pid):
        with Session(engine) as session:
            cards = list_cards(session, "default", project_id=pid)
        return gr.update(
            choices=[(self._card_label(c), str(c.id)) for c in cards], value=None
        )

    @staticmethod
    def _card_label(card: Card) -> str:
        return f"#{card.id} {card.front[:40]}"

    # ==================== 复习 ====================

    def _load_next(self, project_id):
        pid = self._pid(project_id)
        try:
            with Session(engine) as session:
                stats = get_review_stats(session, "default", pid)
                cards = get_due_cards(session, "default", project_id=pid, limit=1)
                if not cards:
                    return (
                        gr.update(value=f"**总卡片数**：{stats['total_cards']}"),
                        gr.update(value="**今日待复习**：0"),
                        gr.update(value=DONE_FRONT),
                        gr.update(value=""),
                        None,
                        None,
                        gr.update(open=False),
                        gr.update(value="✅ 今日复习完成"),
                    )
                card = cards[0]
                return (
                    gr.update(value=f"**总卡片数**：{stats['total_cards']}"),
                    gr.update(value=f"**今日待复习**：{stats['due_count']}"),
                    gr.update(value=f"### {card.front}"),
                    gr.update(value=card.back),
                    card.id,
                    f"review{card.id}-{uuid.uuid4().hex}",
                    gr.update(open=False),
                    gr.update(value="看正面回忆，再展开答案评分"),
                )
        except Exception as e:
            logger.exception("加载卡片失败")
            return self._idle(f"❌ 加载失败：{e}")

    def _load_review(self, project_id):
        result = self._load_next(project_id)
        enabled = bool(result[4]) and not isinstance(result[4], dict)
        return (*result, *(gr.update(interactive=enabled) for _ in range(4)),
                gr.update(interactive=True))

    def _rating_handler(self, rating):
        def handle(card_id, request_id, project_id):
            updates = iter(self._rate(card_id, request_id, rating, project_id))
            first = next(updates)
            yield (*first, *(gr.update(interactive=False) for _ in range(5)))
            last = first
            try:
                for last in updates:
                    yield (*last, *(gr.update(interactive=False) for _ in range(5)))
            finally:
                updates.close()
            next_id = last[4] if not isinstance(last[4], dict) else card_id
            yield (*last, *(gr.update(interactive=bool(next_id)) for _ in range(4)),
                   gr.update(interactive=True))
        return handle

    def _rate(self, card_id, request_id, rating, project_id):
        """保存一次 → 刷新统计 → 下一张 → 隐藏答案。"""
        if not card_id:
            yield self._idle("⚠️ 请先点击「📥 加载下一张」")
            return

        # 第一段 yield: 提交中状态 (连接保持打开, 按钮保持禁用)
        yield (
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
            card_id,
            request_id,
            gr.update(),
            gr.update(value=f"⏳ 正在记录「{RATING_LABEL.get(rating, rating)}」..."),
        )

        pid = self._pid(project_id)
        try:
            with Session(engine) as session:
                current = session.get(Card, int(card_id))
                if current is None or (pid is not None and current.project_id != pid):
                    yield self._load_next(project_id)
                    return
                review_card(
                    session, int(card_id), rating, "default", request_id=request_id
                )
                stats = get_review_stats(session, "default", pid)
                cards = get_due_cards(session, "default", project_id=pid, limit=1)
                next_card = cards[0] if cards else None
                if next_card is not None:
                    front = f"### {next_card.front}"
                    next_id = next_card.id
                    next_req = f"review{next_card.id}-{uuid.uuid4().hex}"
                else:
                    front = DONE_FRONT
                    next_id = None
                    next_req = None
                due = stats["due_count"]
                total = stats["total_cards"]
        except Exception as e:
            logger.exception("复习失败")
            yield self._idle(f"❌ 复习失败：{e}")
            return

        yield (
            gr.update(value=f"**总卡片数**：{total}"),
            gr.update(value=f"**今日待复习**：{due}"),
            gr.update(value=front),
            gr.update(value=next_card.back if next_card else ""),
            next_id,
            next_req,
            gr.update(open=False),
            gr.update(value=f"✅ 已记录「{RATING_LABEL.get(rating, rating)}」"),
        )

    def _idle(self, status):
        """8 项输出，全部保持原状，只更新状态行。"""
        return (
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(open=False),
            gr.update(value=status or ""),
        )

    # ==================== 卡片工具 ====================

    def _generate_cards(self, project_id, node_id, count):
        if not node_id:
            return gr.update(), "⚠️ 请先选择知识点（上面选一个项目后会出现）"
        try:
            with Session(engine) as session:
                node = session.get(KnowledgeNode, int(node_id))
                if node is None:
                    return gr.update(), "⚠️ 知识点不存在"
                cards = generate_cards_from_node(
                    session,
                    node.id,
                    "default",
                    node.description or "",
                    count=int(count),
                )
                pid = self._pid(project_id) or node.project_id
                all_cards = list_cards(session, "default", project_id=pid)
        except Exception as e:
            logger.exception("生成卡片失败")
            return gr.update(), f"❌ 生成失败：{e}"

        if not cards:
            return (
                gr.update(choices=[(self._card_label(c), str(c.id)) for c in all_cards]),
                "⚠️ AI 没有返回可用卡片，可直接重试或换个知识点。",
            )
        return (
            gr.update(
                choices=[(self._card_label(c), str(c.id)) for c in all_cards],
                value=str(cards[0].id),
            ),
            f"✅ 已生成 {len(cards)} 张卡片，可在下方预览并修改措辞。",
        )

    def _reload_cards(self, project_id):
        try:
            return self._card_choices(self._pid(project_id))
        except Exception as e:
            logger.exception("刷新卡片失败")
            return gr.update()

    def _on_card_pick(self, card_id):
        if not card_id:
            return "", ""
        try:
            with Session(engine) as session:
                card = session.get(Card, int(card_id))
                if card is None:
                    return "", ""
                return card.front, card.back
        except Exception:
            logger.exception("读取卡片失败")
            return "", ""

    def _save_card(self, card_id, front, back):
        if not card_id:
            return gr.update(), "⚠️ 请先选择一张卡片"
        try:
            with Session(engine) as session:
                card = update_card(session, int(card_id), front, back, "default")
                pid = card.project_id
                choices = [
                    (self._card_label(c), str(c.id))
                    for c in list_cards(session, "default", project_id=pid)
                ]
            return (
                gr.update(choices=choices, value=str(card.id)),
                "✅ 已保存修改",
            )
        except Exception as e:
            logger.exception("保存卡片失败")
            return gr.update(), f"❌ 保存失败：{e}"
