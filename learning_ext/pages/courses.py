"""统一的我的课程页面。"""

from __future__ import annotations

import html
import json
import logging
import re
from pathlib import Path

import gradio as gr
from ktem.db.engine import engine
from sqlmodel import Session, select

from learning_ext.db.models import KnowledgeNode, LearningProject
from learning_ext.pages.path_generator import PathGeneratorPage
from learning_ext.pages.study_workbench import (
    RESOURCE_EMPTY_MD,
    STATUS_LABEL,
    STATUS_LEARNING,
    STATUS_MASTERED,
    STATUS_SKIPPED,
    STATUS_PENDING,
    WORD_LOOKUP_JS,
    StudyWorkbenchPage,
)
from learning_ext.progress.study import get_project_progress, sort_nodes_by_code

logger = logging.getLogger(__name__)


COURSE_CSS = """
<style>
#learning-course-page,
#learning-course-page > .prose,
#learning-course-page > .wrap {
    width: 100% !important;
    max-width: none !important;
}
#le-course-layout {
    display: grid !important;
    grid-template-columns: 300px minmax(0, 1fr);
    gap: 20px !important;
    align-items: stretch !important;
    height: calc(100dvh - 48px);
    min-height: 0;
    overflow: hidden !important;
}
#le-course-catalog,
#le-course-main {
    min-width: 0 !important;
    box-sizing: border-box;
}
#le-course-catalog {
    height: 100%;
    min-height: 0 !important;
    flex-wrap: nowrap !important;
    align-content: stretch !important;
    overflow-y: auto !important;
    padding: 20px !important;
    background: var(--le-card) !important;
    border: 1px solid var(--le-border) !important;
    border-radius: 18px !important;
}
#le-course-main {
    display: block !important;
    height: 100%;
    min-height: 0 !important;
    overflow-y: auto !important;
    padding: 4px 4px 32px !important;
}
#le-course-main > .gr-block,
#le-course-main > .form,
#le-course-main > .gradio-accordion {
    flex: 0 0 auto !important;
    width: 100% !important;
    max-width: none !important;
}
#le-course-catalog > *,
#le-course-catalog > .form,
#le-course-catalog > .gr-block {
    flex: 0 0 auto !important;
    min-height: 0 !important;
}
#le-course-title {
    margin: 0 !important;
    padding: 0 !important;
    border: 0 !important;
}
#le-course-title h1,
#le-course-title h2,
#le-course-title h3 {
    border: 0 !important;
    padding: 0 !important;
    margin: 0 !important;
}
#le-course-progress {
    margin: 16px 0 20px;
}
.le-course-summary {
    margin: 12px 0 0;
    color: var(--le-text-muted);
    font-size: 13px;
}
.le-course-summary details {
    border: 1px solid var(--le-border);
    border-radius: 12px;
    background: #FFFFFF;
}
.le-course-summary summary {
    padding: 10px 12px;
    color: var(--le-primary-dark);
    font-weight: 700;
    cursor: pointer;
}
.le-course-summary-body {padding: 0 12px 12px; line-height: 1.6;}
.le-course-meta {margin-top: 10px; font-size: 12px;}
.le-course-progress-track {
    height: 8px;
    overflow: hidden;
    background: #EEF2F6;
    border-radius: 99px;
}
.le-course-progress-value {
    height: 100%;
    background: var(--le-primary);
    border-radius: inherit;
    transition: width .2s ease;
}
.le-course-progress-caption {
    display: flex;
    justify-content: space-between;
    margin-top: 8px;
    color: var(--le-text-muted);
    font-size: 12px;
}
#le-course-catalog .gr-radio,
#le-course-catalog .gr-radio > label {
    border: 0 !important;
    box-shadow: none !important;
    background: transparent !important;
}
#le-course-catalog .gr-radio {
    margin: 0 0 18px !important;
    padding: 0 !important;
    min-height: 0 !important;
    flex: 0 0 auto !important;
}
#le-course-catalog .gr-radio .wrap,
#le-course-catalog .gr-radio fieldset,
#le-course-catalog .gr-radio .form {
    height: auto !important;
    min-height: 0 !important;
    overflow: visible !important;
}
#le-course-stage-base,
#le-course-stage-strengthen,
#le-course-stage-sprint {
    position: relative !important;
    display: block !important;
    flex: 0 0 auto !important;
    width: 100% !important;
    height: auto !important;
    min-height: 0 !important;
    max-height: none !important;
    overflow: visible !important;
    opacity: 1 !important;
    visibility: visible !important;
}
#le-course-stage-base > div,
#le-course-stage-strengthen > div,
#le-course-stage-sprint > div,
#le-course-stage-base fieldset,
#le-course-stage-strengthen fieldset,
#le-course-stage-sprint fieldset {
    position: relative !important;
    display: block !important;
    width: 100% !important;
    height: auto !important;
    min-height: 0 !important;
    max-height: none !important;
    overflow: visible !important;
    opacity: 1 !important;
    visibility: visible !important;
}
#le-course-stage-base label,
#le-course-stage-strengthen label,
#le-course-stage-sprint label {
    position: relative !important;
    display: flex !important;
    align-items: flex-start !important;
    width: 100% !important;
    height: auto !important;
    min-height: 38px !important;
    opacity: 1 !important;
    visibility: visible !important;
}
#le-course-catalog .wrap {
    border: 0 !important;
    box-shadow: none !important;
    padding: 0 !important;
}
#le-course-catalog .wrap label {
    padding: 9px 10px !important;
    border-radius: 9px !important;
    color: var(--le-text) !important;
}
#le-course-catalog .wrap label:hover {
    background: var(--le-selected) !important;
}
#le-course-catalog .wrap label:has(input:checked) {
    background: var(--le-selected) !important;
    color: var(--le-primary-dark) !important;
    font-weight: 700 !important;
}
#le-course-catalog .wrap input {
    accent-color: var(--le-primary) !important;
}
#le-course-overview,
#le-course-content,
#le-course-management,
#le-course-create {
    width: 100% !important;
    box-sizing: border-box;
}
#le-course-overview {
    flex: 0 0 auto !important;
    min-height: 0 !important;
    padding: 22px 24px !important;
    background: var(--le-card) !important;
    border: 1px solid var(--le-border) !important;
    border-radius: 18px !important;
}
#le-course-overview .prose {max-width: none !important;}
.le-overview-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 18px;
    margin-bottom: 18px;
}
.le-overview-kicker {
    margin: 0 0 4px;
    color: var(--le-primary);
    font-size: 12px;
    font-weight: 800;
    letter-spacing: .08em;
}
.le-overview-head h1 {margin: 0 !important; font-size: 24px !important;}
.le-overview-topic {margin: 6px 0 0; color: var(--le-text-muted);}
.le-overview-total {
    flex: 0 0 auto;
    padding: 8px 12px;
    border-radius: 999px;
    background: var(--le-selected);
    color: var(--le-primary-dark);
    font-weight: 700;
    white-space: nowrap;
}
.le-stage-block + .le-stage-block {margin-top: 18px;}
.le-stage-heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
}
.le-stage-heading h3 {margin: 0 !important; font-size: 15px !important;}
.le-stage-heading span {color: var(--le-text-muted); font-size: 12px;}
.le-stage-strip {
    display: flex;
    gap: 10px;
    overflow-x: auto;
    padding: 2px 2px 10px;
    scroll-snap-type: x proximity;
}
.le-node-card {
    flex: 0 0 230px;
    min-height: 128px;
    padding: 14px;
    border: 1px solid var(--le-border);
    border-radius: 13px;
    background: #FFFFFF;
    scroll-snap-align: start;
}
.le-node-card-top {display: flex; justify-content: space-between; gap: 8px;}
.le-node-code {color: var(--le-primary); font-size: 12px; font-weight: 800;}
.le-node-state {color: var(--le-text-muted); font-size: 11px; white-space: nowrap;}
.le-node-card h4 {margin: 8px 0 5px; font-size: 14px; line-height: 1.35;}
.le-node-card p {
    display: -webkit-box;
    min-height: 36px;
    margin: 0 0 10px;
    overflow: hidden;
    color: var(--le-text-muted);
    font-size: 12px;
    line-height: 1.5;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
}
.le-overview-node {
    width: auto !important;
    min-width: 0 !important;
    min-height: 30px !important;
    padding: 5px 10px !important;
    border-color: var(--le-border) !important;
    border-radius: 8px !important;
    color: var(--le-primary-dark) !important;
    font-size: 12px !important;
    font-weight: 700 !important;
}
#le-course-content {
    flex: 0 0 auto !important;
    margin-top: 16px !important;
    padding: 22px 24px !important;
    background: var(--le-card) !important;
    border: 1px solid var(--le-border) !important;
    border-radius: 18px !important;
}
#le-course-content > .tabitem {padding: 18px 0 !important;}
#le-course-content,
#le-course-content-tabs {
    overflow: visible !important;
}
#le-chapter-metadata {display: none !important;}
#le-course-catalog .le-catalog-heading {
    flex: 0 0 100%;
    width: 100%;
    margin: 18px 0 8px !important;
    padding: 0 8px !important;
    border: 0 !important;
    color: var(--le-primary-dark);
    font-size: 16px;
}
#le-course-catalog h4.le-catalog-heading {font-size: 14px; color: var(--le-text-muted);}
#le-course-content-tabs > .tab-nav {
    position: sticky !important;
    top: 0;
    z-index: 20;
    background: var(--le-card, #FFFFFF) !important;
    box-shadow: 0 3px 8px rgba(15, 23, 42, .08);
    flex-wrap: nowrap !important;
    overflow-x: auto;
}
#le-course-content-tabs > .tab-nav button {flex-shrink: 0;}
#le-guide-md blockquote {
    background: #EAF0F9;
    border-left: 4px solid #5274AE;
    border-radius: 0 12px 12px 0;
    padding: 16px 20px;
    color: inherit;
}
#le-course-content .prose,
#le-course-content .md {max-width: none !important;}
#le-course-content .prose h1,
#le-course-content .prose h2 {border: 0 !important; padding-left: 0 !important;}
#le-course-management,
#le-course-create {
    margin-top: 16px !important;
}
#le-course-management .table-wrap {
    height: 360px !important;
    min-height: 360px !important;
    max-height: 360px !important;
    overflow: auto !important;
    scrollbar-gutter: stable;
}
#le-course-management table {border-radius: 0 !important; overflow: visible !important;}
#le-course-management thead {
    position: sticky !important;
    top: 0 !important;
    z-index: 2 !important;
}
#le-course-management thead,
#le-course-management thead th,
#le-course-management thead .cell-wrap {
    background: #111827 !important;
    color: #FFFFFF !important;
}
#le-course-management thead button,
#le-course-management thead span {
    background: transparent !important;
    color: #FFFFFF !important;
}
#le-course-management .cm-editor {
    height: 360px !important;
    min-height: 360px !important;
    max-height: 360px !important;
}
#le-course-management .cm-scroller {
    overflow: auto !important;
    scrollbar-gutter: stable;
}
#le-course-main .le-status-row {align-items: center !important;}
#le-course-main .le-status-row button {min-width: 112px !important;}
#le-course-main #le-selected-term {
    position: absolute !important;
    width: 1px !important;
    height: 1px !important;
    opacity: 0 !important;
    overflow: hidden !important;
    pointer-events: none !important;
}
#le-course-empty {
    padding: 24px 0;
    color: var(--le-text-muted);
}
#le-course-switch-status {
    min-height: 0 !important;
    margin: 8px 0 0 !important;
    color: var(--le-text-muted) !important;
    font-size: 12px !important;
}
@media (max-width: 1050px) {
    #le-course-layout {grid-template-columns: 260px minmax(0, 1fr); gap: 14px !important;}
    #le-course-catalog {padding: 16px !important;}
    #le-course-overview, #le-course-content {padding: 18px !important;}
}
@media (max-width: 760px) {
    #le-course-layout {
        display: flex !important;
        height: auto;
        min-height: calc(100dvh - 32px);
        overflow: visible !important;
        flex-direction: column !important;
    }
    #le-course-catalog {height: auto; max-height: 42dvh;}
    #le-course-main {height: auto; overflow: visible !important;}
    .le-overview-head {display: block;}
    .le-overview-total {display: inline-block; margin-top: 10px;}
}
</style>
"""


class CoursePage(StudyWorkbenchPage):
    """把路线生成、课程目录和学习内容放到同一页面。"""

    _handle_generate = PathGeneratorPage._handle_generate
    _handle_refine = PathGeneratorPage._handle_refine
    _handle_save_with_setup = PathGeneratorPage._handle_save_with_setup
    _handle_load = PathGeneratorPage._handle_load
    _handle_export_roadmap = PathGeneratorPage._handle_export_roadmap
    _handle_import_roadmap = PathGeneratorPage._handle_import_roadmap
    _handle_delete_project = PathGeneratorPage._handle_delete_project
    _handle_audit_project = PathGeneratorPage._handle_audit_project
    _parse_audit_project_ids = staticmethod(PathGeneratorPage._parse_audit_project_ids)
    _roadmap_to_markdown = staticmethod(PathGeneratorPage._roadmap_to_markdown)
    _audit_to_markdown = staticmethod(PathGeneratorPage._audit_to_markdown)

    def on_building_ui(self):
        gr.HTML(COURSE_CSS)
        with gr.Row(elem_id="le-course-layout", equal_height=False):
            with gr.Column(elem_id="le-course-catalog", scale=0, min_width=260):
                gr.Markdown("## 我的课程", elem_id="le-course-title")
                self.project_id = gr.Dropdown(
                    label="当前课程",
                    choices=[],
                    value=None,
                    interactive=True,
                    elem_id="le-course-project-picker",
                )
                self.course_info = gr.HTML(
                    "还没有学习项目。请到「首页」生成路线，创建第一门课程。",
                    elem_id="le-course-empty",
                )
                self.course_progress = gr.HTML("", elem_id="le-course-progress")
                self.switch_status = gr.Markdown("", elem_id="le-course-switch-status")
                gr.Markdown("### 课程目录")
                self.base_nodes = gr.Radio(
                    label="课节",
                    show_label=False,
                    choices=[],
                    value=None,
                    interactive=True,
                    elem_id="le-course-stage-base",
                )
                self.strengthen_nodes = gr.HTML("", elem_id="le-chapter-metadata")
                self.sprint_nodes = gr.State(None)

            with gr.Column(elem_id="le-course-main", scale=1):
                self.course_overview = gr.State("")
                self.progress_display = gr.Markdown("", visible=False)
                self.env_status = gr.State("")

                with gr.Column(elem_id="le-course-content", scale=0):
                    self.selected_term = gr.Textbox(
                        elem_id="le-selected-term",
                        visible=True,
                        interactive=True,
                        show_label=False,
                    )
                    self.node_header = gr.Markdown(
                        "*选择左侧知识点开始学习*", elem_id="le-center-content"
                    )
                    with gr.Tabs(elem_id="le-course-content-tabs"):
                        with gr.TabItem("学习内容"):
                            self.node_guide = gr.Markdown("", elem_id="le-guide-md")
                            with gr.Row(elem_classes=["le-status-row"]):
                                self.regen_node_btn = gr.Button("重新生成本节")
                                self.audit_node_btn = gr.Button("审计本节")
                            self.regen_node_status = gr.Markdown("")
                            self.refresh_lesson_btn = gr.Button("刷新正文")
                            self.lesson_timer = gr.Timer(3)
                            with gr.Accordion("完整性审计报告", open=False):
                                self.audit_node_output = gr.Markdown("")
                        with gr.TabItem("练习"):
                            with gr.Row():
                                self.gen_practice_btn = gr.Button("生成实操课程")
                                self.gen_practice_status = gr.Markdown("")
                            self.practice_md = gr.Markdown(
                                "*选择知识点后，可生成对应实操课程。*"
                            )
                        with gr.TabItem("笔记"):
                            self.note_snapshot = gr.State("")
                            self.note_input = gr.Textbox(
                                label="笔记",
                                placeholder="记录理解、疑问、总结……",
                                lines=12,
                                show_label=False,
                            )
                            with gr.Row():
                                self.save_note_btn = gr.Button("保存笔记", variant="primary")
                                self.note_status = gr.Markdown("")
                        with gr.TabItem("资料"):
                            with gr.Row():
                                self.gen_resources_btn = gr.Button("拉取参考资料")
                                self.gen_resources_status = gr.Markdown("")
                            self.resources_md = gr.Markdown(RESOURCE_EMPTY_MD)
                            with gr.Accordion("手动抓取 URL", open=False):
                                with gr.Row():
                                    self.resource_preview_url = gr.Textbox(
                                        label="URL", show_label=False, scale=3
                                    )
                                    self.preview_btn = gr.Button("抓取正文", scale=1)
                                self.resource_preview = gr.Markdown("")
                        with gr.TabItem("AI 助手"):
                            self.chatbot = gr.Chatbot(
                                label="",
                                height=320,
                                type="messages",
                                show_label=False,
                            )
                            self.chat_input = gr.Textbox(
                                placeholder="基于当前知识点提问……",
                                show_label=False,
                                lines=2,
                            )
                            with gr.Row():
                                self.chat_send_btn = gr.Button("发送", variant="primary")
                                self.chat_clear_btn = gr.Button("清空")
                            self.append_chat_to_lesson_btn = gr.Button("并入本节正文")
                            self.append_chat_status = gr.Markdown("")

                    with gr.Accordion("划词解释", open=False):
                        self.term_explain_btn = gr.Button("解释选中词汇")
                        self.term_explain_output = gr.Markdown("")

                    with gr.Row(elem_classes=["le-status-row"]):
                        self.start_btn = gr.Button("标记学习中")
                        self.master_btn = gr.Button("标记已掌握", variant="primary")
                        self.skip_btn = gr.Button("跳过")
                    self.action_status = gr.Markdown("")

    def build_home_ui(self):
        gr.Markdown("# 首页\n创建新的学习路线。")
        self.created_project_id = gr.State(None)
        with gr.Accordion(
            "生成新路线",
            open=True,
            elem_id="le-course-create",
        ):
            gr.Markdown("输入学习目标，生成后可先查看详情，再保存为课程。")
            with gr.Row():
                with gr.Column(scale=3):
                    self.topic_input = gr.Textbox(
                        label="选题",
                        placeholder="例如：从零学习 Transformer 原理",
                        lines=2,
                    )
                with gr.Column(scale=2):
                    self.background_input = gr.Textbox(
                        label="学习背景（可选）",
                        placeholder="如：有 Python 基础，懂基本神经网络",
                        lines=2,
                    )
            with gr.Row():
                self.goal_input = gr.Textbox(
                    label="学习目标（可选）",
                    placeholder="如：能看懂论文并实现一个小 GPT",
                    scale=2,
                )
                self.hours_input = gr.Slider(
                    label="每周投入时间（小时）",
                    minimum=1,
                    maximum=40,
                    value=10,
                    step=1,
                )
            with gr.Row():
                self.generate_btn = gr.Button("生成路线", variant="primary")
                self.regenerate_btn = gr.Button("重新生成")
            self.save_btn = gr.Button("保存并开始学习", variant="primary")
            self.save_progress = gr.Markdown("")
            self.status = gr.Markdown("")
            with gr.Accordion("路线详情", open=False):
                self.roadmap_output = gr.Markdown(
                    "*生成后的路线会显示在这里。*",
                    elem_classes=["learning-roadmap"],
                )
            with gr.Accordion("高级：调整路线 / 查看 JSON", open=False):
                self.roadmap_json = gr.Code(
                    language="json",
                    label="路线 JSON",
                    elem_id="learning-roadmap-json",
                )
                self.refine_input = gr.Textbox(
                    label="调整意见（自然语言）",
                    placeholder="如：增加分布式训练内容；把难度调低",
                )
                self.refine_btn = gr.Button("按意见调整路线")

        with gr.Accordion(
            "项目管理",
            open=False,
            elem_id="le-course-management",
        ):
            self.load_list_btn = gr.Button("刷新课程目录")
            with gr.Accordion("内容管理", open=False):
                with gr.Row():
                    self.regen_all_btn = gr.Button("补全缺失内容")
                    self.regen_all_force_btn = gr.Button(
                        "强制重生成全部", variant="stop"
                    )
                self.regen_all_status = gr.Markdown("")
            with gr.Accordion("添加知识点", open=False):
                self.add_title = gr.Textbox(label="标题", lines=1)
                with gr.Row():
                    self.add_stage = gr.Dropdown(
                        label="阶段",
                        choices=[
                            ("基础", "base"),
                            ("强化", "strengthen"),
                            ("冲刺", "sprint"),
                        ],
                        value="base",
                    )
                    self.add_code = gr.Textbox(label="编号", lines=1)
                with gr.Row():
                    self.add_difficulty = gr.Slider(
                        label="难度", minimum=1, maximum=5, value=3, step=1
                    )
                    self.add_hours = gr.Number(label="预估学时", value=2, precision=0)
                self.add_desc = gr.Textbox(label="说明", lines=2)
                with gr.Row():
                    self.add_ai_btn = gr.Button("AI 生成教学内容")
                    self.add_btn = gr.Button("添加知识点", variant="primary")
                self.add_status = gr.Markdown("")
            gr.Markdown("### 我的学习项目")
            self.project_list = gr.Dataframe(
                elem_id="learning-project-list",
                height=360,
                headers=["ID", "标题", "选题", "进度", "状态", "创建时间"],
                datatype=["number", "str", "str", "str", "str", "str"],
                interactive=False,
                value=[],
            )
            with gr.Row():
                self.refresh_btn = gr.Button("刷新项目列表")
                self.load_project_id = gr.Number(label="加载项目 ID", value=0, precision=0)
                self.load_btn = gr.Button("加载路线")
            with gr.Accordion("导入 / 导出路线", open=False):
                with gr.Row():
                    self.export_project_id = gr.Number(
                        label="导出项目 ID", value=0, precision=0
                    )
                    self.export_roadmap_btn = gr.Button("导出路线")
                self.export_roadmap_file = gr.File(
                    label="下载 JSON", interactive=False
                )
                self.import_roadmap_file = gr.File(
                    label="导入 JSON", file_types=[".json"]
                )
                self.import_roadmap_btn = gr.Button("导入路线", variant="primary")
            with gr.Accordion("路线审计", open=False):
                self.audit_project_id = gr.Textbox(
                    label="项目 ID（留空=全部）", lines=1
                )
                self.audit_project_btn = gr.Button("审计并重生成", variant="primary")
                self.audit_project_output = gr.Markdown("")
            with gr.Accordion("删除项目", open=False):
                with gr.Row():
                    self.delete_project_id = gr.Number(
                        label="删除项目 ID", value=0, precision=0
                    )
                    self.delete_confirm = gr.Textbox(
                        label="确认文本", placeholder="DELETE", lines=1
                    )
                    self.delete_btn = gr.Button("删除项目", variant="stop")


    def _project_rows(self):
        return PathGeneratorPage._refresh_projects(self)

    def _refresh_projects(self):
        return self._project_rows()

    @staticmethod
    def _project_choices(session):
        projects = session.exec(
            select(LearningProject).order_by(LearningProject.id.desc())
        ).all()
        return projects, [
            (f"{p.title or p.topic[:28]}  ·  #{p.id}", str(p.id)) for p in projects
        ]

    def _catalog_updates(self, session, project_id, preferred_id=None):
        if not project_id:
            return (
                gr.update(choices=[], value=None),
                gr.update(value=""),
                None,
                None,
            )
        nodes = self._build_nodes_data(session, int(project_id))
        from learning_ext.course_catalog import chapter_metadata

        project = session.get(LearningProject, int(project_id))
        metadata = chapter_metadata(project, nodes)
        choices = []
        for node in nodes:
            status = node.get("status", STATUS_PENDING)
            icon = {
                STATUS_MASTERED: "✓",
                STATUS_LEARNING: "•",
                STATUS_SKIPPED: "–",
                STATUS_PENDING: "○" if node.get("learnable") else "·",
            }.get(status, "○")
            label = f"{icon}  {node.get('code', '')}  {node.get('title', '')}"
            choices.append((label, str(node.get("id"))))
        all_nodes = [n for n in nodes]
        selected = str(preferred_id) if preferred_id else (
            str(all_nodes[0]["id"]) if all_nodes else None
        )
        if selected not in {value for _, value in choices}:
            selected = choices[0][1] if choices else None
        return (
            gr.update(choices=choices, value=selected),
            gr.update(value='<div data-chapters="' + html.escape(json.dumps(metadata, ensure_ascii=False), quote=True) + '"></div>'),
            None,
            selected,
        )

    @staticmethod
    def _progress_html(progress):
        pct = float(progress.get("pct", 0) or 0)
        done = progress.get("done", 0)
        total = progress.get("total", 0)
        return (
            '<div class="le-course-progress-track">'
            f'<div class="le-course-progress-value" style="width:{max(0, min(100, pct))}%"></div>'
            "</div>"
            '<div class="le-course-progress-caption">'
            f'<span>学习进度</span><span>{done}/{total} · {pct:g}%</span>'
            "</div>"
        )

    def _course_info(self, project, progress):
        if project is None:
            return (
                '<div class="le-course-summary">还没有学习项目。'
                "请到「首页」生成路线，创建第一门课程。</div>"
            )
        details = []
        if project.goal:
            details.append(f"<p><strong>目标：</strong>{html.escape(project.goal)}</p>")
        if project.background:
            details.append(
                f"<p><strong>背景：</strong>{html.escape(project.background)}</p>"
            )
        detail_html = "".join(details) or "<p>暂无补充说明。</p>"
        return (
            '<div class="le-course-summary">'
            "<details><summary>课程简介</summary>"
            f'<div class="le-course-summary-body">{detail_html}</div></details>'
            f'<div class="le-course-meta">每周 {project.weekly_hours:g} 小时 · '
            f"{progress['total']} 个知识点</div></div>"
        )

    @staticmethod
    def _plain_summary(value, limit=84):
        text = re.sub(r"```.*?```", " ", str(value or ""), flags=re.S)
        text = re.sub(r"[#>*_`\[\]()|-]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return "查看本节学习目标、要点与实操内容。"
        return text if len(text) <= limit else f"{text[:limit].rstrip()}…"

    def _overview(self, project, progress, session):
        return ""

    def _empty_view(self):
        return [
            None,
            "*选择左侧知识点开始学习*",
            "",
            "*选择知识点后，可生成对应实操课程。*",
            "",
            "",
            RESOURCE_EMPTY_MD,
            [],
            [],
        ]

    def _node_view(self, node_id):
        view = list(self._on_node_select(node_id))
        view.insert(5, view[4])
        return view

    def _course_reload(self, project_id=None):
        with Session(engine) as session:
            projects, choices = self._project_choices(session)
            requested = int(project_id) if project_id else None
            project = session.get(LearningProject, requested) if requested else None
            if project is None and projects:
                project = projects[0]
            pid = project.id if project else None
            progress = get_project_progress(session, pid) if pid else {
                "total": 0, "done": 0, "learning": 0, "pending": 0, "pct": 0
            }
            catalog = self._catalog_updates(session, pid)
            if project and catalog[3]:
                view = self._node_view(catalog[3])
            else:
                view = self._empty_view()
            return [
                gr.update(choices=choices, value=str(pid) if pid else None),
                self._course_info(project, progress),
                self._progress_html(progress) if project else "",
                catalog[0], catalog[1], catalog[2],
                self._overview(project, progress, session),
                self._build_progress_md(progress) if project else "",
                pid,
                "",
                *view,
            ]

    def _load_created_course(self, project_id):
        if not project_id:
            return [gr.update() for _ in range(19)]
        return self._course_reload(project_id)

    def _save_changed_note(
        self,
        current_node_id,
        current_project_id,
        note_content,
        note_snapshot,
    ):
        if not current_node_id or str(note_content or "") == str(note_snapshot or ""):
            return True, ""
        try:
            nid = int(current_node_id)
            pid = int(current_project_id)
        except (TypeError, ValueError):
            return False, "⚠️ 切换已取消：当前课程上下文无效，笔记仍保留在编辑框中。"
        with Session(engine) as session:
            node = session.get(KnowledgeNode, nid)
            if node is None or node.project_id != pid:
                return False, "⚠️ 切换已取消：知识点归属已变化，笔记仍保留在编辑框中。"
        try:
            message = self._save_note(nid, pid, note_content or "")
        except Exception:
            logger.exception("切换前保存笔记失败")
            return False, "⚠️ 保存失败，操作已取消，笔记仍保留在编辑框中。"
        if message.startswith("✅"):
            return True, "✅ 未保存笔记已自动保存。"
        return False, f"⚠️ 切换已取消：{message}，笔记仍保留在编辑框中。"

    def _prepare_course_action(self, node_id, project_id, content, snapshot):
        saved, notice = self._save_changed_note(node_id, project_id, content, snapshot)
        if not saved:
            raise gr.Error(notice)
        return content, notice

    def _course_change(
        self, project_id, current_node_id, current_project_id,
        note_content, note_snapshot,
    ):
        restore = gr.update(value=str(current_project_id) if current_project_id else None)
        if not project_id:
            return [restore, *[gr.update() for _ in range(18)], gr.update()]
        if current_project_id and str(project_id) == str(current_project_id):
            return [gr.update() for _ in range(20)]
        saved, notice = self._save_changed_note(
            current_node_id, current_project_id, note_content, note_snapshot,
        )
        if not saved:
            return [restore, *[gr.update() for _ in range(18)], notice]
        return [*self._course_reload(project_id), notice]

    def _node_change_course(
        self,
        node_id,
        current_node_id,
        current_project_id,
        note_content,
        note_snapshot,
    ):
        if not node_id or str(node_id) == str(current_node_id):
            return [gr.update() for _ in range(13)]
        with Session(engine) as session:
            try:
                node = session.get(KnowledgeNode, int(node_id))
                expected_project_id = (
                    int(current_project_id) if current_project_id else None
                )
            except (TypeError, ValueError):
                node = None
                expected_project_id = None
            if node is None:
                return [gr.update() for _ in range(12)] + ["⚠️ 知识点不存在。"]
            if expected_project_id and node.project_id != expected_project_id:
                return [gr.update() for _ in range(12)] + [
                    "⚠️ 已忽略不属于当前课程的过期选择。"
                ]
            target_project_id = node.project_id
        saved, notice = self._save_changed_note(
            current_node_id,
            current_project_id,
            note_content,
            note_snapshot,
        )
        if not saved:
            with Session(engine) as session:
                catalog = self._catalog_updates(
                    session,
                    current_project_id,
                    current_node_id,
                )
            return [
                *[gr.update() for _ in range(9)],
                catalog[0],
                catalog[1],
                catalog[2],
                notice,
            ]
        view = self._node_view(node_id)
        with Session(engine) as session:
            catalog = self._catalog_updates(session, target_project_id, node_id)
        return [*view, catalog[0], catalog[1], catalog[2], notice]

    def _status_change(self, node_id, status):
        message, _, _ = self._set_status(node_id, status)
        if not node_id:
            return message, *[gr.update() for _ in range(7)]
        with Session(engine) as session:
            node = session.get(KnowledgeNode, int(node_id))
            if node is None:
                return message, *[gr.update() for _ in range(7)]
            project = session.get(LearningProject, node.project_id)
            progress = get_project_progress(session, node.project_id)
            catalog = self._catalog_updates(session, node.project_id, node_id)
            overview = self._overview(project, progress, session)
            header = self._build_node_header(node, project)
        return (
            message,
            self._build_progress_md(progress),
            catalog[0],
            catalog[1],
            catalog[2],
            self._progress_html(progress),
            overview,
            header,
        )

    def _save_note_course(self, node_id, project_id, content):
        message = self._save_note(node_id, project_id, content)
        snapshot = content if message.startswith("✅") else gr.update()
        return message, snapshot

    def _add_node_course(self, project_id, title, desc, stage, code, difficulty, hours):
        message, _, progress = self._add_node(
            project_id, title, desc, stage, code, difficulty, hours
        )
        with Session(engine) as session:
            catalog = self._catalog_updates(session, project_id)
        return message, catalog[0], catalog[1], catalog[2], progress

    def _add_node_with_ai_course(
        self, project_id, title, desc, stage, code, difficulty, hours
    ):
        message, _, progress = self._add_node_with_ai(
            project_id, title, desc, stage, code, difficulty, hours
        )
        with Session(engine) as session:
            catalog = self._catalog_updates(session, project_id)
        return message, catalog[0], catalog[1], catalog[2], progress

    def course_outputs(self):
        return [
            self.project_id,
            self.course_info,
            self.course_progress,
            self.base_nodes,
            self.strengthen_nodes,
            self.sprint_nodes,
            self.course_overview,
            self.progress_display,
            self.current_project_id,
            self.env_status,
            self.current_node_id,
            self.node_header,
            self.node_guide,
            self.practice_md,
            self.note_input,
            self.note_snapshot,
            self.resources_md,
            self.chatbot,
            self._chat_history,
        ]

    def on_register_events(self):
        asset_dir = Path(__file__).parents[1].joinpath("assets")
        self._app.app.load(
            None,
            None,
            None,
            js=asset_dir.joinpath("workbench.js").read_text(encoding="utf-8"),
        )
        full_outputs = self.course_outputs()
        def guarded_click(button):
            return button.click(
                fn=self._prepare_course_action,
                inputs=[self.current_node_id, self.current_project_id,
                        self.note_input, self.note_snapshot],
                outputs=[self.note_snapshot, self.switch_status],
                concurrency_id="course-context-switch",
                concurrency_limit=1,
            )

        self.project_id.input(
            fn=self._course_change,
            inputs=[
                self.project_id,
                self.current_node_id,
                self.current_project_id,
                self.note_input,
                self.note_snapshot,
            ],
            outputs=[*full_outputs, self.switch_status],
            trigger_mode="always_last",
            concurrency_limit=1,
            concurrency_id="course-context-switch",
            show_progress="hidden",
        )
        for radio in (self.base_nodes,):
            radio.change(
                fn=self._node_change_course,
                inputs=[
                    radio,
                    self.current_node_id,
                    self.current_project_id,
                    self.note_input,
                    self.note_snapshot,
                ],
                outputs=[
                    self.current_node_id,
                    self.node_header,
                    self.node_guide,
                    self.practice_md,
                    self.note_input,
                    self.note_snapshot,
                    self.resources_md,
                    self.chatbot,
                    self._chat_history,
                    self.base_nodes,
                    self.strengthen_nodes,
                    self.sprint_nodes,
                    self.switch_status,
                ],
                trigger_mode="always_last",
                concurrency_limit=1,
                concurrency_id="course-context-switch",
                show_progress="hidden",
            )

        from learning_ext.lesson_jobs import status as lesson_status
        self.lesson_timer.tick(
            fn=lesson_status, inputs=[self.current_node_id],
            outputs=[self.regen_node_status], queue=False, show_progress="hidden",
        )
        self.refresh_lesson_btn.click(
            fn=self._refresh_lesson_body, inputs=[self.current_node_id],
            outputs=[self.node_guide], show_progress="hidden",
            concurrency_id="course-context-switch", concurrency_limit=1,
        )
        self.regen_node_btn.click(
            fn=self._regen_current_node,
            inputs=[self.current_node_id, self.current_project_id],
            outputs=[self.regen_node_status, self.node_header, self.node_guide],
        )
        self.audit_node_btn.click(
            fn=self._audit_current_node,
            inputs=[self.current_node_id],
            outputs=[self.audit_node_output],
        )
        self.save_note_btn.click(
            fn=self._save_note_course,
            inputs=[self.current_node_id, self.current_project_id, self.note_input],
            outputs=[self.note_status, self.note_snapshot],
        )
        self.gen_practice_btn.click(
            fn=self._gen_practice_lesson,
            inputs=[self.current_node_id, self.current_project_id],
            outputs=[self.practice_md, self.gen_practice_status],
        )
        self.gen_resources_btn.click(
            fn=self._gen_resources,
            inputs=[self.current_node_id, self.current_project_id],
            outputs=[self.resources_md, self.gen_resources_status],
        )
        self.preview_btn.click(
            fn=self._preview_resource,
            inputs=[self.resource_preview_url],
            outputs=[self.resource_preview],
        )
        self.selected_term.change(
            fn=self._on_term_selected,
            inputs=[self.selected_term, self.current_node_id],
            outputs=[self.term_explain_output],
        )
        self.term_explain_btn.click(
            fn=self._on_term_selected_manual,
            inputs=[self.selected_term, self.current_node_id],
            outputs=[self.term_explain_output],
        )
        self.chat_send_btn.click(
            fn=self._chat_send,
            inputs=[self.chat_input, self.current_node_id, self._chat_history],
            outputs=[self.chatbot, self._chat_history, self.chat_input],
        )
        self.chat_input.submit(
            fn=self._chat_send,
            inputs=[self.chat_input, self.current_node_id, self._chat_history],
            outputs=[self.chatbot, self._chat_history, self.chat_input],
        )
        self.chat_clear_btn.click(
            fn=lambda: ([], [], ""),
            outputs=[self.chatbot, self._chat_history, self.chat_input],
        )
        self.append_chat_to_lesson_btn.click(
            fn=self._append_last_assistant_to_node,
            inputs=[self.current_node_id, self._chat_history],
            outputs=[self.node_guide, self.append_chat_status],
        )
        self.start_btn.click(
            fn=lambda nid: self._status_change(nid, STATUS_LEARNING),
            inputs=[self.current_node_id],
            outputs=[
                self.action_status,
                self.progress_display,
                self.base_nodes,
                self.strengthen_nodes,
                self.sprint_nodes,
                self.course_progress,
                self.course_overview,
                self.node_header,
            ],
        )
        self.master_btn.click(
            fn=lambda nid: self._status_change(nid, STATUS_MASTERED),
            inputs=[self.current_node_id],
            outputs=[
                self.action_status,
                self.progress_display,
                self.base_nodes,
                self.strengthen_nodes,
                self.sprint_nodes,
                self.course_progress,
                self.course_overview,
                self.node_header,
            ],
        )
        self.skip_btn.click(
            fn=lambda nid: self._status_change(nid, STATUS_SKIPPED),
            inputs=[self.current_node_id],
            outputs=[
                self.action_status,
                self.progress_display,
                self.base_nodes,
                self.strengthen_nodes,
                self.sprint_nodes,
                self.course_progress,
                self.course_overview,
                self.node_header,
            ],
        )
        self._app.app.load(
            fn=self._course_reload,
            outputs=full_outputs,
            js=WORD_LOOKUP_JS,
        )
        course_tab = getattr(self._app, "_tabs", {}).get("learning-course-tab")
        if course_tab is not None:
            course_tab.select(fn=self._course_reload, outputs=full_outputs)
