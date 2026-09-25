"""Course content completeness audit."""

from __future__ import annotations

from typing import Iterable

from sqlmodel import Session, select

from learning_ext.db.models import KnowledgeEdge, KnowledgeNode, LearningProject
from learning_ext.llm import chat
from learning_ext.notes import get_resources
from learning_ext.progress.study import course_code_sort_key


def _node_outline(nodes: Iterable[KnowledgeNode]) -> str:
    lines = []
    for node in sorted(nodes, key=lambda n: course_code_sort_key(n.code)):
        desc = (node.description or "").strip().replace("\n", " ")
        if len(desc) > 180:
            desc = desc[:180] + "..."
        lines.append(
            f"- [{node.code}] {node.title} | stage={node.stage} | "
            f"difficulty={node.difficulty}/5 | est={node.est_hours}h | {desc}"
        )
    return "\n".join(lines)


def _dependency_context(session: Session, project_id: int, node: KnowledgeNode) -> str:
    edges = session.exec(
        select(KnowledgeEdge).where(KnowledgeEdge.project_id == project_id)
    ).all()
    nodes = session.exec(
        select(KnowledgeNode).where(KnowledgeNode.project_id == project_id)
    ).all()
    by_id = {n.id: n for n in nodes}
    prereq = [by_id[e.target_id] for e in edges if e.source_id == node.id and e.target_id in by_id]
    next_nodes = [
        by_id[e.source_id] for e in edges if e.target_id == node.id and e.source_id in by_id
    ]
    return (
        "【前置知识】\n"
        + (_node_outline(prereq) or "无明确前置知识")
        + "\n\n【后续依赖本节的知识】\n"
        + (_node_outline(next_nodes) or "无明确后续依赖")
    )


def _resource_context(session: Session, node_id: int) -> str:
    resources = get_resources(session, node_id)
    if not resources:
        return "暂无已抓取参考资料。"
    lines = []
    for idx, res in enumerate(resources, 1):
        if res.rtype == "summary":
            continue
        preview = (res.preview or "").strip()
        if len(preview) > 1200:
            preview = preview[:1200] + "..."
        lines.append(
            f"【资料{idx}】{res.title}\n"
            f"URL: {res.url or '无'}\n"
            f"定位: {res.description or '无'}\n"
            f"正文摘录: {preview or '未抓取到正文'}"
        )
    return "\n\n".join(lines) if lines else "暂无已抓取参考资料。"


def audit_node_content(session: Session, node_id: int) -> str:
    """Audit whether a generated lesson is complete enough for self-study."""
    node = session.get(KnowledgeNode, int(node_id))
    if node is None:
        raise ValueError(f"Knowledge node {node_id} not found")
    project = session.get(LearningProject, node.project_id)
    if project is None:
        raise ValueError(f"Project {node.project_id} not found")

    project_nodes = session.exec(
        select(KnowledgeNode).where(KnowledgeNode.project_id == project.id)
    ).all()
    lesson = node.description or ""
    prompt = f"""请审计下面这节 AI 生成教材是否完整、全面、细节足够。你不是改写教材，而是做质量审计。

【项目主题】
{project.topic}

【学习目标】
{project.goal or "未填写"}

【当前知识点】
[{node.code}] {node.title}
难度：{node.difficulty}/5
预计学时：{node.est_hours}h

【全路线知识地图】
{_node_outline(project_nodes)}

{_dependency_context(session, project.id, node)}

【已抓取参考资料与摘要】
{_resource_context(session, node.id)}

【当前教材正文】
{lesson[:14000] if lesson else "当前教材为空。"}

请用 Markdown 输出审计报告，必须包含：

## 结论
- 覆盖率评分：0-100
- 是否适合直接学习：是/否/勉强
- 一句话判断

## 已覆盖得比较好的内容
列 3-6 条。

## 明显缺失或讲得太浅的内容
列 3-8 条。每条说明为什么重要，以及应该补到什么程度。

## 与前后课程的衔接问题
说明前置知识是否假设过多，后续知识是否铺垫不足。

## 是否需要拆分或扩写
如果需要，给出建议拆分成哪些小节；如果不需要，说明原因。

## 必做自测/实践
给出 5 道能验证本节是否真的学会的问题或小任务。

## 下一步建议
给学习者一个具体行动清单。

要求：直接、挑剔、具体。不要为了鼓励而降低标准。"""
    return chat(
        prompt,
        system=(
            "你是严苛的课程质量审稿人和学习路径设计师。"
            "你专门发现教材遗漏、浅讲、结构不合理和实践不足的问题。"
        ),
        temperature=0.2,
        max_tokens=2200,
    )
