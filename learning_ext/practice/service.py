"""环境搭建 / 实操辅助。

针对编程/工具类选题，AI 生成：
    - 环境清单 (需安装的软件/依赖)
    - 分步搭建命令
    - 实操练习项目
并落库为 Task。
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from learning_ext.db.models import KnowledgeNode, Task
from learning_ext.llm import chat_json

SYSTEM = """你是一位资深技术导师。为给定的学习主题生成实操方案。
返回 JSON：
{
  "env_setup": [
    {"name": "软件/工具名", "purpose": "用途", "command": "安装命令"}
  ],
  "tasks": [
    {
      "title": "实操任务标题",
      "description": "详细说明 (含命令、步骤、验收标准)",
      "task_type": "env|practice|project"
    }
  ]
}
规则：
- env_setup: 必装的、搭建开发环境所需
- tasks: 3-5 个由浅入深的练习，最后一个应是综合小项目
- 命令要具体可执行，注明操作系统假设 (默认跨平台)
- 只返回 JSON"""


def generate_practice_plan(
    session: Session,
    project_id: int,
    node_id: Optional[int],
    topic: str,
    learner_level: str = "初学者",
    *,
    model_name: Optional[str] = None,
) -> List[Task]:
    """为选题/知识点生成实操方案并落库。"""
    node_ctx = ""
    if node_id:
        node = session.get(KnowledgeNode, node_id)
        if node:
            node_ctx = f"\n【当前知识点】{node.title}: {node.description}"

    prompt = f"""请为以下主题生成实操方案。

【学习主题】{topic}
【学习者水平】{learner_level}{node_ctx}

返回 JSON。"""
    result = chat_json(prompt, system=SYSTEM, model_name=model_name)

    created = []
    # 环境搭建作为 env 任务
    for env in result.get("env_setup", []):
        desc = f"**用途**: {env.get('purpose', '')}\n\n**安装**:\n```\n{env.get('command', '')}\n```"
        t = Task(
            project_id=project_id,
            node_id=node_id,
            title=f"[环境] {env.get('name', '')}",
            description=desc,
            task_type="env",
            status="pending",
        )
        session.add(t)
        created.append(t)

    # 实操任务
    for task in result.get("tasks", []):
        t = Task(
            project_id=project_id,
            node_id=node_id,
            title=task.get("title", "实操任务"),
            description=task.get("description", ""),
            task_type=task.get("task_type", "practice"),
            status="pending",
        )
        session.add(t)
        created.append(t)

    session.commit()
    return created
