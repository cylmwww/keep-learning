from __future__ import annotations

import html

import gradio as gr
from ktem.app import BasePage
from ktem.db.engine import engine
from sqlmodel import Session

from learning_ext.course_management import (
    course_management_snapshot,
    delete_owned_draft,
    delete_owned_project,
)


MANAGEMENT_CSS = """
<style>
#le-course-management {max-width: 1180px; margin: 0 auto; padding: 20px 12px 60px;}
#le-management-stats {display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 14px 0 20px;}
.le-management-stat {padding: 16px 18px; border: 1px solid var(--le-border); border-radius: 14px; background: var(--le-card);}
.le-management-stat strong {display: block; margin-top: 4px; color: var(--le-primary-dark); font-size: 28px;}
.le-management-stat span {color: var(--le-text-muted); font-size: 13px;}
#le-course-management .le-management-section {padding: 18px; border: 1px solid var(--le-border); border-radius: 16px; background: var(--le-card); margin-top: 14px;}
#le-course-management .le-danger-zone {margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--le-border);}
#le-course-management .le-selection-hint {margin: 2px 0 10px; color: var(--le-text-muted); font-size: 13px;}
@media (max-width: 720px) {#le-management-stats {grid-template-columns: 1fr;} }
</style>
"""


class CourseManagementPage(BasePage):
    def __init__(self, app):
        super().__init__(app)
        self.owner_id = "default"

    def on_building_ui(self):
        gr.HTML(MANAGEMENT_CSS)
        with gr.Column(elem_id="le-course-management"):
            gr.Markdown("# 课程管理\n集中管理已经保存的课程，以及创建到一半的课程草稿。")
            self.stats = gr.HTML(self._stats_html(0, 0))
            self.refresh_btn = gr.Button("刷新课程列表")

            with gr.Column(elem_classes=["le-management-section"]):
                gr.Markdown("## 已生成课程")
                gr.Markdown("删除课程会一并清理对应的知识点、学习进度、复习卡片、测验和课节内容。")
                gr.Markdown("使用下方“当前选择”下拉框，或点击表格任意单元格选择课程。", elem_classes=["le-selection-hint"])
                with gr.Row():
                    self.project_choice = gr.Dropdown(
                        label="当前选择", choices=[], value=None, interactive=True, scale=4
                    )
                    self.open_course_btn = gr.Button("前往我的课程", scale=1)
                self.project_status = gr.Markdown("")
                with gr.Accordion("删除所选课程", open=False):
                    with gr.Row(elem_classes=["le-danger-zone"]):
                        self.project_confirm = gr.Textbox(
                            label="删除确认", placeholder="输入 删除", lines=1
                        )
                        self.delete_project_btn = gr.Button("永久删除课程", variant="stop")
                self.project_table = gr.Dataframe(
                    headers=["ID", "课程名称", "原始主题", "课节数", "已掌握", "状态", "更新时间"],
                    datatype=["number", "str", "str", "number", "str", "str", "str"],
                    type="array",
                    interactive=False,
                    value=[],
                    height=240,
                    elem_id="le-management-project-table",
                )

            with gr.Column(elem_classes=["le-management-section"]):
                gr.Markdown("## 未完成草稿")
                gr.Markdown("草稿保存了已完成的调研、问卷答案、课程蓝图和前三节预览，可以继续上次的创建流程。")
                gr.Markdown("使用下方“当前选择”下拉框，或点击表格任意单元格选择草稿。", elem_classes=["le-selection-hint"])
                with gr.Row():
                    self.draft_choice = gr.Dropdown(
                        label="当前选择", choices=[], value=None, interactive=True, scale=4
                    )
                    self.continue_draft_btn = gr.Button(
                        "继续创建课程", variant="primary", scale=1
                    )
                self.draft_status = gr.Markdown("")
                with gr.Accordion("删除所选草稿", open=False):
                    with gr.Row(elem_classes=["le-danger-zone"]):
                        self.draft_confirm = gr.Textbox(
                            label="删除确认", placeholder="输入 删除", lines=1
                        )
                        self.delete_draft_btn = gr.Button("永久删除草稿", variant="stop")
                self.draft_table = gr.Dataframe(
                    headers=["ID", "课程主题", "当前阶段", "完成度", "教材", "更新时间"],
                    datatype=["number", "str", "str", "str", "str", "str"],
                    type="array",
                    interactive=False,
                    value=[],
                    height=240,
                    elem_id="le-management-draft-table",
                )

    @staticmethod
    def _stats_html(projects: int, drafts: int) -> str:
        return (
            '<div id="le-management-stats">'
            f'<div class="le-management-stat"><span>已生成课程</span><strong>{projects}</strong></div>'
            f'<div class="le-management-stat"><span>未完成草稿</span><strong>{drafts}</strong></div>'
            f'<div class="le-management-stat"><span>全部课程资产</span><strong>{projects + drafts}</strong></div>'
            "</div>"
        )

    def _snapshot(self):
        with Session(engine) as session:
            snapshot = course_management_snapshot(session, self.owner_id)
        project_value = snapshot["project_choices"][0][1] if snapshot["project_choices"] else None
        draft_value = snapshot["draft_choices"][0][1] if snapshot["draft_choices"] else None
        return (
            self._stats_html(len(snapshot["projects"]), len(snapshot["drafts"])),
            snapshot["project_rows"],
            gr.update(choices=snapshot["project_choices"], value=project_value),
            snapshot["draft_rows"],
            gr.update(choices=snapshot["draft_choices"], value=draft_value),
        )

    def _delete_project(self, project_id, confirm):
        if not project_id:
            return (*self._snapshot(), "请选择要删除的课程。")
        if (confirm or "").strip() != "删除":
            return (*self._snapshot(), "请输入“删除”后再执行。")
        try:
            with Session(engine) as session:
                delete_owned_project(session, int(project_id), self.owner_id)
            return (*self._snapshot(), f"✅ 课程 #{int(project_id)} 已删除。")
        except Exception as exc:
            return (*self._snapshot(), f"删除失败：{html.escape(str(exc))}")

    def _delete_draft(self, draft_id, confirm):
        if not draft_id:
            return (*self._snapshot(), "请选择要删除的草稿。")
        if (confirm or "").strip() != "删除":
            return (*self._snapshot(), "请输入“删除”后再执行。")
        try:
            with Session(engine) as session:
                delete_owned_draft(session, int(draft_id), self.owner_id)
            return (*self._snapshot(), f"✅ 草稿 #{int(draft_id)} 已删除。")
        except Exception as exc:
            return (*self._snapshot(), f"删除失败：{html.escape(str(exc))}")

    @staticmethod
    def _selected_row(table, evt):
        index = evt.index[0] if isinstance(evt.index, (tuple, list)) else evt.index
        if table is None or index is None or int(index) >= len(table):
            raise gr.Error("没有找到所选行")
        return table[int(index)]

    @classmethod
    def _select_project_row(cls, table, evt: gr.SelectData):
        row = cls._selected_row(table, evt)
        project_id = str(int(row[0]))
        return gr.update(value=project_id), f"✅ 已选择课程：{row[1]}（#{project_id}）"

    @classmethod
    def _select_draft_row(cls, table, evt: gr.SelectData):
        row = cls._selected_row(table, evt)
        draft_id = str(int(row[0]))
        return gr.update(value=draft_id), f"✅ 已选择草稿：{row[1]}（#{draft_id}）"

    def _open_course(
        self,
        project_id,
        current_node_id,
        current_project_id,
        note_content,
        note_snapshot,
    ):
        if not project_id:
            raise gr.Error("请选择课程")
        course = self._app.learning_course_page
        updates = course._course_change(
            project_id,
            current_node_id,
            current_project_id,
            note_content,
            note_snapshot,
        )
        return (*updates, gr.update(selected="learning-course-tab"))

    def _continue_draft(self, draft_id):
        if not draft_id:
            raise gr.Error("请选择草稿")
        creator = self._app.learning_creator_page
        return (*creator._resume_draft(int(draft_id)), gr.update(selected="learning-home-tab"))

    def _snapshot_outputs(self):
        return [
            self.stats,
            self.project_table,
            self.project_choice,
            self.draft_table,
            self.draft_choice,
        ]

    def on_register_events(self):
        snapshot_outputs = self._snapshot_outputs()
        self.refresh_btn.click(fn=self._snapshot, outputs=snapshot_outputs)
        self.project_table.select(
            fn=self._select_project_row,
            inputs=[self.project_table],
            outputs=[self.project_choice, self.project_status],
            show_progress="hidden",
        )
        self.draft_table.select(
            fn=self._select_draft_row,
            inputs=[self.draft_table],
            outputs=[self.draft_choice, self.draft_status],
            show_progress="hidden",
        )
        course = self._app.learning_course_page
        self.open_course_btn.click(
            fn=self._open_course,
            inputs=[
                self.project_choice,
                course.current_node_id,
                course.current_project_id,
                course.note_input,
                course.note_snapshot,
            ],
            outputs=[*course.course_outputs(), course.switch_status, self._app.tabs],
            concurrency_id="course-context-switch",
            concurrency_limit=1,
        )
        self.delete_project_btn.click(
            fn=self._delete_project,
            inputs=[self.project_choice, self.project_confirm],
            outputs=[*snapshot_outputs, self.project_status],
        )
        self.delete_draft_btn.click(
            fn=self._delete_draft,
            inputs=[self.draft_choice, self.draft_confirm],
            outputs=[*snapshot_outputs, self.draft_status],
        )
        creator = self._app.learning_creator_page
        self.continue_draft_btn.click(
            fn=self._continue_draft,
            inputs=[self.draft_choice],
            outputs=[*creator.resume_outputs(), self._app.tabs],
        )
        self._app.app.load(fn=self._snapshot, outputs=snapshot_outputs)
        management_tab = getattr(self._app, "_tabs", {}).get("learning-management-tab")
        if management_tab is not None:
            management_tab.select(fn=self._snapshot, outputs=snapshot_outputs)
