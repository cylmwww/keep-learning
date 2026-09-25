from __future__ import annotations

import html
import json
from pathlib import Path

import gradio as gr
from ktem.app import BasePage
from ktem.db.engine import engine
from sqlmodel import Session

from learning_ext.course_creation import (
    build_blueprint,
    create_draft,
    extract_material,
    generate_preview,
    publish_course,
    refine_blueprint,
    run_research,
)
from learning_ext.course_management import get_owned_draft


CREATOR_CSS = """
<style>
#le-creator {max-width: 1120px; margin: 0 auto; padding: 22px 12px 60px;}
#le-creator .le-step {border: 1px solid var(--le-border); border-radius: 18px; background: var(--le-card); padding: 18px; margin: 14px 0;}
#le-creator .le-step-label {color: var(--le-primary); font-weight: 700; letter-spacing: .02em;}
#le-learning-composer {gap: 0 !important; padding: 12px !important; border: 1px solid var(--le-border); border-radius: 24px; background: var(--le-card); box-shadow: var(--le-shadow);}
#le-learning-composer .form, #le-learning-input, #le-learning-input .wrap {border: 0 !important; background: transparent !important; box-shadow: none !important; padding: 0 !important;}
#le-learning-input textarea {border: 0 !important; box-shadow: none !important; background: transparent !important; padding: 10px 12px !important; resize: vertical;}
#le-learning-composer:focus-within {border-color: var(--le-primary-light);}
#le-composer-actions {align-items: center !important; flex-wrap: nowrap !important; gap: 8px !important; padding-top: 8px;}
#le-material-upload, #le-create-submit {flex: 0 0 40px !important; width: 40px !important; min-width: 40px !important; height: 40px !important; padding: 0 !important; font-size: 0 !important; border: 0 !important; border-radius: 50% !important; box-shadow: none !important;}
#le-material-upload {background: transparent !important; color: var(--le-text) !important;}
#le-material-upload::after {content: "+"; font-size: 28px; line-height: 1;}
#le-material-upload > svg, #le-material-upload > span {display: none !important;}
#le-create-submit::after {content: "↑"; font-size: 26px; line-height: 1;}
#le-material-upload:hover {background: var(--le-selected, #EAF0F8) !important;}
#le-material-upload:focus-visible, #le-create-submit:focus-visible {outline: 2px solid var(--le-primary); outline-offset: 3px;}
#le-material-name {flex: 1 1 0 !important; min-width: 0 !important; color: var(--le-text-muted); font-size: 12px; overflow-wrap: anywhere;}
#le-material-remove {flex: 0 0 auto !important; min-width: 0 !important; padding: 5px 8px !important; font-size: 12px !important;}
#le-blueprint-modal {position: fixed !important; inset: 58px 32px 24px 92px; z-index: 1000; background: white !important; border: 1px solid var(--le-border); border-radius: 20px; box-shadow: 0 22px 80px rgba(15, 23, 42, .25); padding: 20px !important; overflow: auto !important;}
#le-blueprint-modal::before {content: ""; position: fixed; inset: 0; z-index: -1; background: rgba(15, 23, 42, .34);}
#le-blueprint-canvas {transform-origin: top left; transition: transform .15s ease; min-width: 700px; padding: 12px; border-radius: 16px; background-image: radial-gradient(#d8dee9 1px, transparent 1px); background-size: 18px 18px;}
.le-bp-head {padding: 12px 16px; border: 1px solid #cbd7e9; border-radius: 14px; background: #f7faff;}
.le-bp-unit {margin: 16px 0 8px 28px; padding: 12px 14px; border-left: 4px solid var(--le-primary); background: #f8fafc; border-radius: 10px;}
.le-bp-lecture {margin: 8px 0 8px 28px; font-weight: 700; color: #334155;}
.le-bp-lesson {margin: 7px 0 7px 56px; padding: 10px 12px; border: 1px solid #e2e8f0; background: white; border-radius: 10px;}
.le-bp-meta {font-size: 12px; color: #64748b; margin-top: 4px;}
@media (max-width: 760px) {#le-blueprint-modal {inset: 12px;} #le-blueprint-canvas {min-width: 0;} }
</style>
"""


class CourseCreatorPage(BasePage):
    """V2 四步课程创作页面。"""

    def __init__(self, app):
        super().__init__(app)
        self.owner_id = "default"

    def on_building_ui(self):
        gr.HTML(CREATOR_CSS)
        with gr.Column(elem_id="le-creator"):
            gr.Markdown("# 创建一门新课程\n写下一个粗略想法，或上传教材。Keep Learning 会先调研，再与你共同确定课程。")
            self.draft_id = gr.State(None)
            self.questionnaire_state = gr.State("{}")
            self.blueprint_state = gr.State("{}")
            self.created_project_id = gr.State(None)

            with gr.Column(elem_classes=["le-step"]):
                gr.Markdown("<span class='le-step-label'>开始 · 学习内容</span>")
                with gr.Column(elem_id="le-learning-composer"):
                    self.topic_input = gr.Textbox(
                        label="你想学习什么？", show_label=False,
                        placeholder="输入想学习的内容，也可以点击左下角 + 上传教材……",
                        lines=4, elem_id="le-learning-input",
                    )
                    with gr.Row(elem_id="le-composer-actions"):
                        self.material_file = gr.UploadButton(
                            "上传教材", file_count="single",
                            file_types=[".pdf", ".docx", ".txt", ".md", ".markdown"],
                            type="filepath", min_width=40, scale=0,
                            elem_id="le-material-upload",
                        )
                        self.material_name = gr.HTML("", elem_id="le-material-name")
                        self.remove_material_btn = gr.Button(
                            "移除教材", visible=False, scale=0, elem_id="le-material-remove"
                        )
                        self.start_btn = gr.Button(
                            "确认生成", variant="primary", scale=0, min_width=40,
                            elem_id="le-create-submit",
                        )
                self.start_status = gr.Markdown("")

            with gr.Column(visible=False, elem_classes=["le-step"]) as self.research_panel:
                gr.Markdown("<span class='le-step-label'>第 1 步，共 4 步 · 搜索资料与初步构建</span>")
                self.research_output = gr.Markdown("")

            with gr.Column(visible=False, elem_classes=["le-step"]) as self.question_panel:
                gr.Markdown("<span class='le-step-label'>第 2 步，共 4 步 · 了解你的基础和目标</span>")
                gr.Markdown("问题根据刚才的调研结果生成。标注“可多选”的问题可以选择多项。")
                self.question_inputs = []
                for index in range(6):
                    component = gr.CheckboxGroup(
                        label=f"问题 {index + 1}", choices=[], visible=False
                    )
                    self.question_inputs.append(component)
                self.build_blueprint_btn = gr.Button("生成课程蓝图", variant="primary")
                self.question_status = gr.Markdown("")

            with gr.Column(visible=False, elem_classes=["le-step"]) as self.blueprint_panel:
                gr.Markdown("<span class='le-step-label'>第 3 步，共 4 步 · 协商课程蓝图</span>")
                self.blueprint_summary = gr.HTML("")
                with gr.Row():
                    self.open_blueprint_btn = gr.Button("打开课程蓝图", variant="primary")
                    self.generate_preview_btn = gr.Button("确认蓝图，生成前三节")
                self.refine_input = gr.Textbox(
                    label="描述想修改的地方",
                    placeholder="例如：减少理论介绍，增加两个案例，并把练习提前……",
                    lines=3,
                )
                self.refine_btn = gr.Button("按要求修改蓝图")
                self.blueprint_status = gr.Markdown("")

            with gr.Column(visible=False, elem_id="le-blueprint-modal") as self.blueprint_modal:
                with gr.Row():
                    gr.Markdown("## 课程蓝图")
                    self.close_blueprint_btn = gr.Button("关闭", size="sm")
                with gr.Row():
                    self.zoom_out_btn = gr.Button("缩小", size="sm")
                    self.zoom_reset_btn = gr.Button("适应", size="sm")
                    self.zoom_in_btn = gr.Button("放大", size="sm")
                self.blueprint_canvas = gr.HTML("", elem_id="le-blueprint-canvas")

            with gr.Column(visible=False, elem_classes=["le-step"]) as self.preview_panel:
                gr.Markdown("<span class='le-step-label'>第 4 步，共 4 步 · 预览前三节</span>")
                gr.Markdown("只会保存前三节正文；其余课节在学习时按需生成。")
                self.preview_output = gr.Markdown("")
                self.publish_btn = gr.Button(
                    "确认并保存课程", variant="primary", interactive=False, size="lg"
                )
                self.publish_status = gr.Markdown("")

    @staticmethod
    def _file_path(value):
        if not value:
            return None
        if isinstance(value, str):
            return value
        return getattr(value, "name", None) or getattr(value, "path", None)

    def _start_creation(self, topic, material):
        try:
            with Session(engine) as session:
                name, text = extract_material(session, self._file_path(material))
                draft = create_draft(session, self.owner_id, topic or "", name, text)
                draft_id = int(draft.id)
                result = run_research(session, draft_id, self.owner_id)
            question_updates = self._question_updates(result["questions"])
            return (
                draft_id,
                self._research_markdown(result),
                json.dumps({"questions": result["questions"]}, ensure_ascii=False),
                *question_updates,
                gr.update(visible=True),
                gr.update(visible=True),
                "✅ 调研完成，请回答下面的问题。",
            )
        except Exception as exc:
            raise gr.Error(f"创建课程失败：{exc}") from exc

    @staticmethod
    def _question_updates(questions, answers=None):
        answers = answers or {}
        updates = []
        for index in range(6):
            if index >= len(questions):
                updates.append(gr.update(visible=False, choices=[], value=[]))
                continue
            question = questions[index]
            suffix = "（可多选）" if question.get("type") == "multiple" else "（单选）"
            label = f"Q{index + 1} {question['title']} {suffix} · {question['reason']}"
            choices = [
                (f"{option['label']} — {option['description']}", option["value"])
                for option in question["options"]
            ]
            updates.append(
                gr.update(
                    visible=True,
                    label=label,
                    choices=choices,
                    value=list(answers.get(question.get("id"), [])),
                )
            )
        return updates

    @staticmethod
    def _research_markdown(result):
        lines = [
            f"### {result.get('topic') or '课程调研'}",
            str(result.get("summary") or "已完成初步资料整理。"),
        ]
        if result.get("queries"):
            lines.append("\n**搜索词**：" + " · ".join(f"`{q}`" for q in result["queries"]))
        if result.get("sources"):
            lines.append("\n**网络资料**")
            for source in result["sources"]:
                title = str(source.get("title") or source.get("url") or "资料").replace("]", "")
                url = str(source.get("url") or "")
                lines.append(f"- [{title}]({url}) — {source.get('excerpt') or '仅取得搜索摘要'}")
        else:
            lines.append("\n> 暂未取得网络搜索结果；当前初步构建仅依据你的输入和教材。")
        if result.get("suggested_extensions"):
            lines.append("\n**需要你确认的教材外扩展**：" + "；".join(result["suggested_extensions"]))
        return "\n".join(lines)

    @staticmethod
    def _preview_markdown(lessons):
        lines = []
        for index, lesson in enumerate(lessons, 1):
            lines.extend(
                [
                    f"## 预览 {index} · {lesson.get('title') or '未命名课节'}",
                    str(lesson.get("content") or ""),
                    "\n---\n",
                ]
            )
        return "\n".join(lines)

    def resume_outputs(self):
        return [
            self.draft_id,
            self.topic_input,
            self.material_file,
            self.research_output,
            self.questionnaire_state,
            *self.question_inputs,
            self.research_panel,
            self.question_panel,
            self.start_status,
            self.blueprint_state,
            self.blueprint_summary,
            self.blueprint_canvas,
            self.blueprint_panel,
            self.refine_input,
            self.blueprint_status,
            self.preview_output,
            self.publish_btn,
            self.preview_panel,
            self.publish_status,
            self.material_name,
            self.remove_material_btn,
        ]

    def _resume_draft(self, draft_id):
        try:
            with Session(engine) as session:
                draft = get_owned_draft(session, int(draft_id), self.owner_id)
                research = json.loads(draft.research_json or "{}")
                questionnaire = json.loads(draft.questionnaire_json or "{}")
                if draft.status == "researching" and not questionnaire.get("questions"):
                    research = run_research(session, draft.id, self.owner_id)
                    questionnaire = {"questions": research.get("questions", [])}
                answers = json.loads(draft.answers_json or "{}")
                blueprint = json.loads(draft.blueprint_json or "{}")
                preview = json.loads(draft.preview_json or "{}")
                status = draft.status
                topic = draft.input_text
                material_name = draft.material_name

            questions = questionnaire.get("questions", [])
            question_updates = self._question_updates(questions, answers)
            blueprint_html = self._blueprint_html(blueprint) if blueprint.get("units") else ""
            lessons = preview.get("lessons", [])
            has_research = bool(research)
            has_questions = bool(questions)
            has_blueprint = bool(blueprint.get("units"))
            has_preview = bool(lessons)
            material_note = f"，教材“{material_name}”的解析内容仍已保留" if material_name else ""
            return (
                int(draft_id),
                topic,
                None,
                self._research_markdown(research) if has_research else "",
                json.dumps(questionnaire, ensure_ascii=False),
                *question_updates,
                gr.update(visible=has_research),
                gr.update(visible=has_questions),
                f"✅ 已恢复草稿 #{int(draft_id)}{material_note}。",
                json.dumps(blueprint, ensure_ascii=False),
                blueprint_html,
                blueprint_html,
                gr.update(visible=has_blueprint),
                "",
                "可以继续调整蓝图。" if has_blueprint else "",
                self._preview_markdown(lessons),
                gr.update(interactive=has_preview and status == "awaiting_course_confirmation"),
                gr.update(visible=has_preview),
                "前三节预览已恢复，请确认后保存。" if has_preview else "",
                "",
                gr.update(visible=False),
            )
        except Exception as exc:
            raise gr.Error(f"恢复草稿失败：{exc}") from exc

    def _build_blueprint(self, draft_id, questionnaire_json, *selections):
        try:
            questionnaire = json.loads(questionnaire_json or "{}")
            questions = questionnaire.get("questions", [])
            answers = {}
            for question, selected in zip(questions, selections):
                values = list(selected or [])
                if question.get("type") == "single" and len(values) != 1:
                    raise ValueError(f"“{question['title']}”需要且只能选择一项")
                if not values:
                    raise ValueError(f"请回答“{question['title']}”")
                answers[question["id"]] = values
            with Session(engine) as session:
                blueprint = build_blueprint(session, int(draft_id), answers, self.owner_id)
            rendered = self._blueprint_html(blueprint)
            return (
                json.dumps(blueprint, ensure_ascii=False),
                rendered,
                rendered,
                gr.update(visible=True),
                "✅ 课程蓝图已生成。打开查看，或在下方描述修改要求。",
            )
        except Exception as exc:
            raise gr.Error(str(exc)) from exc

    def _refine_blueprint(self, draft_id, instruction):
        try:
            with Session(engine) as session:
                blueprint = refine_blueprint(
                    session, int(draft_id), instruction or "", self.owner_id
                )
            rendered = self._blueprint_html(blueprint)
            return json.dumps(blueprint, ensure_ascii=False), rendered, rendered, "✅ 已生成新的蓝图版本。"
        except Exception as exc:
            raise gr.Error(f"修改蓝图失败：{exc}") from exc

    @staticmethod
    def _blueprint_html(blueprint):
        units = blueprint.get("units", [])
        lesson_count = sum(
            len(lecture.get("lessons", []))
            for unit in units
            for lecture in unit.get("lectures", [])
        )
        parts = [
            '<div class="le-bp-head">',
            f"<h2>{html.escape(str(blueprint.get('title') or '课程蓝图'))}</h2>",
            f"<p>{html.escape(str(blueprint.get('summary') or ''))}</p>",
            f'<div class="le-bp-meta">{len(units)} 个单元 · {lesson_count} 个课节</div></div>',
        ]
        for unit_index, unit in enumerate(units, 1):
            parts.append(f'<div class="le-bp-unit">单元 {unit_index} · {html.escape(str(unit.get("title") or ""))}</div>')
            for lecture_index, lecture in enumerate(unit.get("lectures", []), 1):
                parts.append(f'<div class="le-bp-lecture">讲次 {lecture_index} · {html.escape(str(lecture.get("title") or ""))}</div>')
                for lesson in lecture.get("lessons", []):
                    depth = " · ".join(str(v) for v in lesson.get("depth", []))
                    parts.append(
                        '<div class="le-bp-lesson">'
                        f'<strong>{html.escape(str(lesson.get("code") or ""))} {html.escape(str(lesson.get("title") or ""))}</strong>'
                        f'<div>{html.escape(str(lesson.get("objective") or ""))}</div>'
                        f'<div class="le-bp-meta">{int(lesson.get("minutes") or 45)} 分钟 · {html.escape(depth)}</div></div>'
                    )
        return "".join(parts)

    def _generate_preview(self, draft_id):
        try:
            with Session(engine) as session:
                lessons = generate_preview(session, int(draft_id), self.owner_id)
            return self._preview_markdown(lessons), gr.update(interactive=True), gr.update(visible=True), "✅ 前三节已经生成，请审阅后确认保存。"
        except Exception as exc:
            raise gr.Error(f"生成预览失败：{exc}") from exc

    def _publish(self, draft_id):
        try:
            with Session(engine) as session:
                project_id = publish_course(session, int(draft_id), self.owner_id)
            return (
                project_id,
                f"✅ 课程已保存（项目 #{project_id}）。前三节已就绪，其余课节将在学习时生成。",
                gr.update(selected="learning-course-tab"),
            )
        except Exception as exc:
            raise gr.Error(f"保存课程失败：{exc}") from exc

    def on_register_events(self):
        self.material_file.upload(
            fn=lambda value: (
                html.escape(Path(self._file_path(value)).name) if value else "",
                gr.update(visible=bool(value)),
            ),
            inputs=[self.material_file],
            outputs=[self.material_name, self.remove_material_btn],
        )
        self.remove_material_btn.click(
            fn=lambda: (None, "", gr.update(visible=False)),
            outputs=[self.material_file, self.material_name, self.remove_material_btn],
        )
        self.start_btn.click(
            fn=self._start_creation,
            inputs=[self.topic_input, self.material_file],
            outputs=[
                self.draft_id,
                self.research_output,
                self.questionnaire_state,
                *self.question_inputs,
                self.research_panel,
                self.question_panel,
                self.start_status,
            ],
        )
        self.build_blueprint_btn.click(
            fn=self._build_blueprint,
            inputs=[self.draft_id, self.questionnaire_state, *self.question_inputs],
            outputs=[
                self.blueprint_state,
                self.blueprint_summary,
                self.blueprint_canvas,
                self.blueprint_panel,
                self.question_status,
            ],
        )
        self.open_blueprint_btn.click(
            fn=lambda: gr.update(visible=True), outputs=[self.blueprint_modal]
        )
        self.close_blueprint_btn.click(
            fn=lambda: gr.update(visible=False), outputs=[self.blueprint_modal]
        )
        self.zoom_in_btn.click(
            fn=None,
            js="() => { const e=document.querySelector('#le-blueprint-canvas'); const z=Math.min(1.6,Number(e.dataset.zoom||1)+.1); e.dataset.zoom=z; e.style.transform=`scale(${z})`; }",
        )
        self.zoom_out_btn.click(
            fn=None,
            js="() => { const e=document.querySelector('#le-blueprint-canvas'); const z=Math.max(.6,Number(e.dataset.zoom||1)-.1); e.dataset.zoom=z; e.style.transform=`scale(${z})`; }",
        )
        self.zoom_reset_btn.click(
            fn=None,
            js="() => { const e=document.querySelector('#le-blueprint-canvas'); e.dataset.zoom=1; e.style.transform='scale(1)'; }",
        )
        self.refine_btn.click(
            fn=self._refine_blueprint,
            inputs=[self.draft_id, self.refine_input],
            outputs=[self.blueprint_state, self.blueprint_summary, self.blueprint_canvas, self.blueprint_status],
        )
        self.generate_preview_btn.click(
            fn=self._generate_preview,
            inputs=[self.draft_id],
            outputs=[self.preview_output, self.publish_btn, self.preview_panel, self.blueprint_status],
        )
        self.publish_btn.click(
            fn=self._publish,
            inputs=[self.draft_id],
            outputs=[self.created_project_id, self.publish_status, self._app.tabs],
        )
