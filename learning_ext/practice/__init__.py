"""环境搭建 / 实操辅助模块。"""

from learning_ext.practice.auto_setup import (
    InstallPlan,
    PlanStep,
    build_install_plan,
    execute_plan,
    generate_install_commands,
    plan_from_state,
    plan_to_state,
    render_plan_markdown,
    screen_command,
    workspace_dir,
)
from learning_ext.practice.service import generate_practice_plan

__all__ = [
    "generate_practice_plan",
    "generate_install_commands",
    "build_install_plan",
    "execute_plan",
    "render_plan_markdown",
    "plan_to_state",
    "plan_from_state",
    "screen_command",
    "workspace_dir",
    "InstallPlan",
    "PlanStep",
]
