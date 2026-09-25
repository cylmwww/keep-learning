from __future__ import annotations

import logging

import gradio as gr
import plotly.graph_objects as go
from ktem.app import BasePage
from ktem.db.engine import engine
from sqlmodel import Session

from learning_ext.dashboard import build_dashboard_data, seed_demo_learning_data

logger = logging.getLogger(__name__)


class DashboardPage(BasePage):
    """学习进度看板"""

    def __init__(self, app):
        super().__init__(app)

    def on_building_ui(self):
        gr.Markdown("# 📊 学习看板")
        with gr.Row():
            self.project_id = gr.Dropdown(
                label="项目",
                choices=[],
                value=None,
                interactive=True,
                scale=3,
            )
            self.refresh_btn = gr.Button("🔄 刷新", size="sm", scale=1)
            self.seed_btn = gr.Button("🧪 生成测试数据", size="sm", scale=1)

        self.metric_html = gr.HTML("")

        with gr.Row():
            with gr.Column(scale=2):
                gr.Markdown("### 📌 状态分布")
                self.status_md = gr.Markdown("")
            with gr.Column(scale=3):
                gr.Markdown("### 📅 最近 14 天学习热力")
                self.heatmap = gr.Plot(label="学习分钟")

        gr.Markdown("### 📝 最新学习日报")
        self.report = gr.Markdown("")
        self.status = gr.Markdown("")

    def on_register_events(self):
        outputs = [
            self.project_id,
            self.metric_html,
            self.status_md,
            self.heatmap,
            self.report,
            self.status,
        ]
        self.project_id.change(
            fn=self._load_dashboard,
            inputs=[self.project_id],
            outputs=outputs,
        )
        self.refresh_btn.click(
            fn=self._load_dashboard,
            inputs=[self.project_id],
            outputs=outputs,
        )
        self.seed_btn.click(
            fn=self._seed_demo_data,
            inputs=[],
            outputs=outputs,
        )
        try:
            self._app.app.load(fn=self._load_dashboard, inputs=[], outputs=outputs)
        except Exception as e:
            logger.warning(f"看板初始化事件注册失败: {e}")

    def _seed_demo_data(self):
        with Session(engine) as session:
            project = seed_demo_learning_data(session)
            return self._dashboard_outputs(session, project.id, "✅ 测试数据已生成")

    def _load_dashboard(self, project_id=None):
        pid = self._parse_project_id(project_id)
        with Session(engine) as session:
            return self._dashboard_outputs(session, pid, "")

    def _dashboard_outputs(self, session: Session, project_id: int | None, status: str):
        data = build_dashboard_data(session, project_id=project_id)
        value = str(data["project_id"]) if data["project_id"] is not None else None
        return (
            gr.update(choices=data["projects"], value=value),
            self._render_metrics(data["metrics"]),
            self._render_status(data["status_counts"]),
            self._build_heatmap(data["heatmap"]),
            data["latest_report"],
            status,
        )

    @staticmethod
    def _parse_project_id(project_id):
        if project_id in (None, "", 0):
            return None
        try:
            return int(project_id)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _render_metrics(metrics: dict) -> str:
        avg_mastery = metrics["avg_mastery"] * 100
        return f"""
<div style="display:grid;grid-template-columns:repeat(5,minmax(120px,1fr));gap:12px;margin:12px 0;">
  <div class="le-metric"><span class="val">{metrics["total_nodes"]}</span><span class="lbl">知识点总数</span></div>
  <div class="le-metric"><span class="val">{metrics["mastered_nodes"]}</span><span class="lbl">已掌握</span></div>
  <div class="le-metric"><span class="val">{avg_mastery:.0f}%</span><span class="lbl">平均掌握度</span></div>
  <div class="le-metric"><span class="val">{metrics["week_minutes"]:.0f}</span><span class="lbl">近 7 天分钟</span></div>
  <div class="le-metric"><span class="val">{metrics["due_cards"]}/{metrics["total_cards"]}</span><span class="lbl">到期卡片</span></div>
</div>
"""

    @staticmethod
    def _render_status(status_counts: dict) -> str:
        labels = {
            "mastered": "✅ 已掌握",
            "learning": "📖 学习中",
            "weak": "⚠️ 薄弱",
            "pending": "⏳ 待学",
            "skipped": "⏭ 跳过",
        }
        return "\n".join(
            f"- {labels[key]}：**{status_counts.get(key, 0)}**"
            for key in ["mastered", "learning", "weak", "pending", "skipped"]
        )

    @staticmethod
    def _build_heatmap(rows: list[dict]):
        fig = go.Figure(
            data=[
                go.Bar(
                    x=[row["date"] for row in rows],
                    y=[row["minutes"] for row in rows],
                    marker_color="#4F46E5",
                )
            ]
        )
        fig.update_layout(
            height=280,
            margin=dict(l=24, r=12, t=10, b=30),
            yaxis_title="分钟",
            xaxis_title="",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        return fig
