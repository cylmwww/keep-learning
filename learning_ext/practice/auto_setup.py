"""AI 自动环境配置：生成计划 → 人工审阅 → 确认后执行。

旧实现把模型生成的命令拼成 PowerShell 字符串直接执行，用户看不到计划，
高风险命令也照跑。现在改成三段式：

    1. 环境检测 —— 每条安装步骤带一条只读 check 命令，装过就跳过
    2. 可审阅计划 —— 逐条命令先过白名单/黑名单筛查，输出渲染成 Markdown
    3. 用户确认 —— 确认绑定计划摘要 (sha256)，摘要对不上就不执行

执行侧边界：
    - 只跑筛查通过的步骤；high 风险步骤只打印、不自动执行
    - 子进程固定工作目录、超时、最小环境变量 (不含 API key 等敏感值)
    - 超时结束整棵进程树；失败不继续执行依赖该步骤的后续步骤
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Optional

from learning_ext.llm import LLMOutputError, chat_json
from learning_ext.llm.validate import (
    as_str,
    require_dict,
    require_enum,
    require_list,
    require_str,
)

logger = logging.getLogger(__name__)

DANGER_LEVELS = ("low", "medium", "high")
STEP_KINDS = ("install", "config", "verify", "env")

DEFAULT_STEP_TIMEOUT = 600.0
DEFAULT_CHECK_TIMEOUT = 60.0
MAX_CMD_LEN = 600

SYSTEM_PROMPT = """你是一位 Windows 环境配置专家。用户有一份学习环境配置清单，你的任务是把它转换成**可以逐条审阅、逐条执行**的计划。

输出格式：严格返回一个 JSON 数组，每个元素是一步：
[
  {
    "cmd": "实际执行的命令 (PowerShell 命令，单条，不要用分号拼接)",
    "check": "只读的检测命令，退出码 0 表示这一步已经满足，可直接跳过。没有合适的检测命令就留空字符串",
    "desc": "这条命令做什么 (中文一句话)",
    "danger": "low | medium | high",
    "kind": "install | config | verify | env"
  }
]

规则：
1. 只输出真正必要的步骤，跳过"可选"项
2. install 优先用声明式软件包操作，并用 check 判断是否已安装：
   check 例：winget list --id Python.Python.3.12
   cmd   例：winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
   常见 winget ID：Python=Python.Python.3.12, Node.js=OpenJS.NodeJS.LTS, Git=Git.Git, VSCode=Microsoft.VisualStudioCode, Docker=Docker.DockerDesktop, Rust=Rustlang.Rustup, Go=GoLang.Go, Java=EclipseAdoptium.Temurin.21.JDK
3. 设置环境变量用 PowerShell: [Environment]::SetEnvironmentVariable('Name','Value','User')
4. 创建目录: New-Item -ItemType Directory -Force -Path <path>
5. 实操代码不要装进全局环境：需要 Python 依赖时先建独立虚拟环境
   (python -m venv .venv)，后续装包用 .venv 里的 pip
6. danger=high 标记可能破坏现有环境的命令 (卸载、覆盖系统变量、改注册表)
7. 只允许单条命令。不要用 ; | && > < 拼接或重定向，不要调用 cmd /c、Invoke-Expression、curl
8. 如果清单是理论类主题无需环境配置，返回空数组 []
9. 只返回 JSON，不要任何解释、不要 markdown 代码块标记"""


# ==================== 命令筛查 ====================

# 只读检测命令 (check 字段只能用这些)
_READONLY_PATTERNS = [
    r"^winget\s+(list|show|search)\b",
    r"^pip3?\s+(list|show|freeze)\b",
    r"^python3?(\.\d+)?\s+-m\s+pip\s+(list|show)\b",
    r"^python3?(\.\d+)?\s+(--version|-V)\b",
    r"^py\s+(-\d(\.\d+)?\s+)?(--version|-V)\b",
    r"^git\s+--version\b",
    r"^node\s+(--version|-v)\b",
    r"^npm\s+(--version|-v)\b",
    r"^docker\s+--version\b",
    r"^go\s+version\b",
    r"^rustc\s+--version\b",
    r"^cargo\s+--version\b",
    r"^javac?\s+-version\b",
    r"^code\s+--version\b",
    r"^Test-Path\b",
    r"^Get-Command\b",
    r"^Get-ItemProperty\b",
    r"^where(\.exe)?\s",
]

# 可执行的写入命令 (cmd 字段只能用这些)
_WRITE_PATTERNS = [
    r"^\.?[\\/]?\.venv[\\/]Scripts[\\/](pip|python)(\.exe)?\s+",
    r"^winget\s+install\b",
    r"^pip3?\s+install\b",
    r"^python3?(\.\d+)?\s+-m\s+(pip\s+install|venv)\b",
    r"^py\s+(-\d(\.\d+)?\s+)?-m\s+(pip\s+install|venv)\b",
    r"^New-Item\s+-ItemType\s+Directory\b",
    r"^\[Environment\]::SetEnvironmentVariable\(",
    r"^Set-Location\b",
    r"^git\s+clone\b",
    r"^npm\s+(install|i|ci)\b",
    r"^cargo\s+install\b",
    r"^go\s+install\b",
]

# 无论是否命中白名单都拒绝的构造：命令拼接、重定向、下载执行、破坏性操作
_DENIED_TOKENS = (
    ";",
    "&&",
    "||",
    "|",
    "`",
    "$(",
    "${",
    ">",
    "<",
    "\n",
    "\r",
    "&",
)

_DENIED_COMMANDS = (
    "remove-item",
    "remove-",
    "uninstall",
    "rmdir",
    "del ",
    "erase ",
    "format-",
    "stop-process",
    "start-process",
    "invoke-",
    "iex",
    "iwr",
    "curl",
    "wget",
    "reg ",
    "reg.exe",
    "regedit",
    "set-executionpolicy",
    "cmd ",
    "cmd.exe",
    "shutdown",
    "schtasks",
    "takeown",
    "icacls",
    "bcdedit",
    "diskpart",
    "net user",
)


def screen_command(cmd: str, *, readonly: bool) -> Optional[str]:
    """返回 None 表示通过，否则返回拒绝原因。"""
    text = (cmd or "").strip()
    if not text:
        return "空命令"
    if len(text) > MAX_CMD_LEN:
        return f"命令过长 (>{MAX_CMD_LEN} 字符)"
    low = text.lower()
    env_setting = re.fullmatch(
        r"\[Environment\]::SetEnvironmentVariable\('[A-Za-z_][A-Za-z0-9_]*','[A-Za-z0-9_ .:\\\\/-]*','User'\)",
        text, re.IGNORECASE,
    )
    if any(c in text for c in "$(){}@") and not (env_setting and not readonly):
        return "不允许表达式、变量展开或脚本块"
    if re.match(r"^Set-Location\b", text, re.IGNORECASE):
        return "工作目录由项目固定，不能通过步骤改变"
    if re.match(r"^\.?[\\/]?\.venv[\\/]Scripts[\\/]", text, re.IGNORECASE):
        if not re.fullmatch(
            r"\.?[\\/]?\.venv[\\/]Scripts[\\/](?:pip(?:\.exe)?\s+install|python(?:\.exe)?\s+-m\s+pip\s+install)\s+[A-Za-z0-9_.,=<>!~+:/\\ -]+",
            text, re.IGNORECASE,
        ):
            return "虚拟环境仅允许使用 pip install 安装依赖"
    for token in _DENIED_TOKENS:
        if token in text:
            return f"含被禁止的构造 `{token}`"
    for banned in _DENIED_COMMANDS:
        if banned in low:
            return f"含被禁止的操作 `{banned.strip()}`"
    patterns = _READONLY_PATTERNS if readonly else _WRITE_PATTERNS
    if not any(re.match(p, text, re.IGNORECASE) for p in patterns):
        return "不在允许的命令白名单内"
    return None


# ==================== 计划 ====================


@dataclass
class PlanStep:
    index: int
    cmd: str
    desc: str
    danger: str = "low"
    kind: str = "install"
    check: str = ""
    depends_on: list[int] = field(default_factory=list)
    allowed: bool = True
    blocked_reason: str = ""

    def to_canonical(self) -> dict:
        return {
            "index": self.index,
            "cmd": self.cmd,
            "desc": self.desc,
            "danger": self.danger,
            "kind": self.kind,
            "check": self.check,
            "depends_on": list(self.depends_on),
            "allowed": self.allowed,
        }


@dataclass
class InstallPlan:
    steps: list[PlanStep]
    digest: str
    source_digest: str = ""

    @property
    def executable_count(self) -> int:
        return sum(1 for s in self.steps if s.allowed and s.danger != "high")


def _plan_digest(steps: Iterable[PlanStep]) -> str:
    payload = json.dumps(
        [s.to_canonical() for s in steps], ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_install_commands(env_checklist_md: str, background: str = "") -> list[dict]:
    """让 AI 把环境清单转成计划步骤（未经筛查，需经 build_install_plan）。"""
    prompt = f"""请把以下环境配置清单转换成 Windows 可执行计划。

【学习者背景】{background or "未知"}

【环境配置清单】
{env_checklist_md}

请输出计划 JSON 数组。"""
    result = chat_json(prompt, system=SYSTEM_PROMPT)
    if isinstance(result, dict) and "commands" in result:
        result = result.get("commands")
    if isinstance(result, dict) and "steps" in result:
        result = result.get("steps")
    if not isinstance(result, list):
        raise LLMOutputError(
            f"安装计划应为 JSON 数组，实际为 {type(result).__name__}"
        )
    return result


def _enum_or(item: dict, key: str, field: str, allowed, default: str) -> str:
    """字段缺失或为 null 时用默认值；出现了就必须是合法取值。"""
    value = item.get(key)
    if value is None:
        return default
    return require_enum(value, field, allowed)


def _parse_step(raw: dict, index: int) -> PlanStep:
    field = f"steps[{index}]"
    item = require_dict(raw, field)
    # 不截断命令：超长命令由 screen_command 显式拦截, 而不是悄悄改动内容后执行
    cmd = require_str(item.get("cmd"), f"{field}.cmd")
    desc = as_str(item.get("desc"), f"{field}.desc", default="", max_len=200) or cmd
    danger = _enum_or(item, "danger", f"{field}.danger", DANGER_LEVELS, "low")
    kind = _enum_or(item, "kind", f"{field}.kind", STEP_KINDS, "install")
    check = as_str(item.get("check"), f"{field}.check", default="")

    depends_on: list[int] = []
    raw_deps = item.get("depends_on")
    if raw_deps is not None:
        deps = require_list(raw_deps, f"{field}.depends_on")
        for j, dep in enumerate(deps):
            if isinstance(dep, bool) or not isinstance(dep, int):
                raise LLMOutputError(
                    f"字段 `{field}.depends_on[{j}]` 类型错误：期望 integer"
                )
            if not 1 <= dep <= index:
                raise LLMOutputError(
                    f"字段 `{field}.depends_on[{j}]` 必须引用之前的步骤 (1..{index})"
                )
            depends_on.append(dep - 1)  # 对外 1-based, 内部 0-based

    step = PlanStep(
        index=index,
        cmd=cmd,
        desc=desc,
        danger=danger,
        kind=kind,
        check=check,
        depends_on=depends_on,
    )

    reason = screen_command(cmd, readonly=False)
    if reason:
        step.allowed = False
        step.blocked_reason = reason
    elif check:
        check_reason = screen_command(check, readonly=True)
        if check_reason:
            step.check = ""
            logger.info("检测命令未通过筛查, 已忽略: %s", check_reason)
    return step


def build_install_plan(
    raw_commands: list, *, source_digest: str = ""
) -> InstallPlan:
    """把模型输出转成可审阅、可执行、带摘要的计划。

    Raises:
        LLMOutputError: 模型输出的结构无法解析
    """
    if not isinstance(raw_commands, list):
        raise LLMOutputError(
            f"安装计划应为 JSON 数组，实际为 {type(raw_commands).__name__}"
        )

    steps: list[PlanStep] = []
    for i, raw in enumerate(raw_commands):
        try:
            step = _parse_step(raw, len(steps))
        except LLMOutputError as e:
            logger.warning("丢弃第 %s 步不合规的计划: %s", i + 1, e)
            continue
        # 未显式声明依赖时按顺序线性依赖: 上一步失败则本步不执行
        if not step.depends_on and steps:
            step.depends_on = [steps[-1].index]
        steps.append(step)

    return InstallPlan(steps=steps, digest=_plan_digest(steps), source_digest=source_digest)


def plan_to_state(plan: InstallPlan) -> dict:
    """计划 → 可放进 gr.State 的纯字典 (UI 只持有它)。"""
    return {
        "digest": plan.digest,
        "source_digest": plan.source_digest,
        "steps": [s.to_canonical() for s in plan.steps],
    }


def plan_from_state(state: dict) -> InstallPlan:
    """状态字典 → 计划。摘要按内容重算，用来比对确认时看到的摘要。"""
    steps = [
        PlanStep(
            index=s["index"],
            cmd=s["cmd"],
            desc=s["desc"],
            danger=s["danger"],
            kind=s["kind"],
            check=s["check"],
            depends_on=list(s.get("depends_on") or []),
            allowed=s["allowed"],
            blocked_reason=s.get("blocked_reason", ""),
        )
        for s in (state.get("steps") or [])
    ]
    return InstallPlan(
        steps=steps,
        digest=_plan_digest(steps),
        source_digest=state.get("source_digest", ""),
    )


DANGER_ICON = {"low": "🟢", "medium": "🟡", "high": "🔴"}
KIND_LABEL = {
    "install": "安装",
    "config": "配置",
    "verify": "校验",
    "env": "环境",
}


def render_plan_markdown(plan: InstallPlan) -> str:
    """把计划渲染成用户审阅用的 Markdown。"""
    if not plan.steps:
        return "✅ 该学习主题无需配置环境，可直接开始学习。"

    lines = [
        f"**共 {len(plan.steps)} 步，其中可自动执行 {plan.executable_count} 步。**",
        "",
        f"计划摘要：`{plan.digest[:16]}`",
        "",
    ]
    for s in plan.steps:
        icon = DANGER_ICON.get(s.danger, "🟢")
        label = KIND_LABEL.get(s.kind, s.kind)
        lines.append(f"**{s.index + 1}. {icon} [{label}] {s.desc}**")
        lines.append("")
        if s.check:
            lines.append(f"- 检测：`{s.check}`")
        lines.append(f"- 命令：`{s.cmd}`")
        if not s.allowed:
            lines.append(f"- ⛔ **已拦截**：{s.blocked_reason}")
        elif s.danger == "high":
            lines.append("- ⚠️ **高风险，不会自动执行**，请手动确认后自行运行")
        lines.append("")
    lines.append(
        "> 只有你点击「✅ 确认并执行此计划」后才会启动子进程；"
        "计划摘要变化后需要重新确认。"
    )
    return "\n".join(lines)


# ==================== 执行 ====================

# 最小必要环境变量：显式白名单，避免把 API key 之类的敏感值带进子进程
_ENV_ALLOWLIST = {
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "SYSTEMDRIVE",
    "COMSPEC",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
}


def minimal_env() -> dict:
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper() in _ENV_ALLOWLIST and v is not None
    }
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def workspace_dir(project_id: Optional[int] = None) -> Path:
    """项目的实操工作目录 (命令在这里执行，虚拟环境也建在这里)。"""
    override = os.environ.get("LE_WORKSPACE_DIR")
    if override:
        base = Path(override)
    else:
        try:
            from flowsettings import KH_APP_DATA_DIR

            base = Path(str(KH_APP_DATA_DIR))
        except Exception:
            base = Path(__file__).resolve().parents[2] / ".runtime"
    name = f"project_{int(project_id)}" if project_id is not None else "_default"
    path = base / "le_workspace" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def _kill_tree(proc: subprocess.Popen) -> None:
    """结束整棵进程树 (winget/msi 会拉起子进程)。"""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=20,
                check=True,
            )
        else:
            proc.kill()
    except Exception:
        logger.warning("结束进程树失败, pid=%s", proc.pid)
        try:
            proc.kill()
        except Exception:
            pass


def _run_command(
    cmd: str, *, cwd: str, timeout: float, env: dict
) -> Iterator[object]:
    """逐行 yield 输出字符串，最后 yield ("__exit__", returncode, timed_out)。"""
    import queue
    import threading

    command = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            cmd,
        ]
    pip_match = re.fullmatch(
        r"(?:pip3?|python3?(?:\.\d+)?\s+-m\s+pip|py\s+(?:-\d(?:\.\d+)?\s+)?-m\s+pip|\.?[\\/]?\.venv[\\/]Scripts[\\/](?:pip(?:\.exe)?|python(?:\.exe)?\s+-m\s+pip))\s+install\s+(.+)",
        cmd, re.IGNORECASE,
    )
    if pip_match:
        root = Path(cwd).resolve()
        python = (root / ".venv" / "Scripts" / "python.exe").resolve()
        if not python.is_relative_to(root) or not python.is_file():
            yield "项目虚拟环境不存在或路径无效，请先创建 .venv。\n"
            yield ("__exit__", 1, False)
            return
        arguments = shlex.split(pip_match.group(1), posix=False)
        if any(arg.startswith("-") for arg in arguments):
            yield "项目依赖安装仅接受软件包及版本，不接受额外安装参数。\n"
            yield ("__exit__", 1, False)
            return
        command = [str(python), "-m", "pip", "install", *arguments]
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        cwd=cwd,
        env=env,
        creationflags=_CREATE_NEW_PROCESS_GROUP,
    )

    lines: "queue.Queue" = queue.Queue()

    def _pump() -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                lines.put(line)
        except Exception:
            pass
        finally:
            lines.put(None)

    threading.Thread(target=_pump, daemon=True).start()

    deadline = time.monotonic() + timeout
    timed_out = False
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            break
        try:
            item = lines.get(timeout=min(0.5, remaining))
        except queue.Empty:
            continue
        if item is None:
            break
        text = item.rstrip()
        if text:
            yield text + "\n"

    if timed_out:
        yield f"[超时] 超过 {int(timeout)}s，正在结束进程树...\n"
        _kill_tree(proc)

    try:
        proc.wait(timeout=max(0.1, min(5, deadline - time.monotonic())))
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
        proc.wait(timeout=5)
    yield ("__exit__", proc.returncode, timed_out)


# 步骤终态
_OK = "ok"
_FAILED = "failed"
_TIMEOUT = "timeout"
_SKIPPED = "skipped"  # 被截断 / 依赖未满足
_SATISFIED = "satisfied"
_MANUAL = "manual"
_BLOCKED = "blocked"

_STOPPING_STATES = {_FAILED, _TIMEOUT, _SKIPPED, _MANUAL, _BLOCKED}


def execute_plan(
    plan: InstallPlan,
    confirmed_digest: Optional[str],
    *,
    workdir: Optional[str] = None,
    timeout: float = DEFAULT_STEP_TIMEOUT,
) -> Iterator[str]:
    """确认后执行计划。未确认或摘要不匹配时不会启动任何子进程。"""
    if not plan.steps:
        yield "✅ 该学习主题无需配置环境，可直接开始学习。\n"
        return

    if not confirmed_digest:
        yield "⛔ 计划未经确认，未执行任何命令。请先点「✅ 确认并执行此计划」。\n"
        return
    if confirmed_digest != _plan_digest(plan.steps):
        yield (
            "⛔ 计划摘要与确认时不符（计划已被替换或修改），未执行任何命令。"
            "请重新生成计划并重新确认。\n"
        )
        return

    try:
        if workdir is None:
            cwd_path = workspace_dir(None)
        else:
            cwd_path = Path(workdir)
            cwd_path.mkdir(parents=True, exist_ok=True)
        cwd = str(cwd_path)
    except Exception as e:
        yield f"❌ 无法准备工作目录：{e}\n"
        return

    env = minimal_env()
    status: dict[int, str] = {}
    ok = failed = 0

    yield f"工作目录：`{cwd}`\n\n"
    yield f"共 {len(plan.steps)} 步，开始执行...\n\n"

    for step in plan.steps:
        header = f"━━━ [{step.index + 1}/{len(plan.steps)}] {step.desc} ━━━\n"
        yield header

        reason = screen_command(step.cmd, readonly=False)
        if reason or (step.check and screen_command(step.check, readonly=True)):
            status[step.index] = _BLOCKED
            yield "⛔ 已拦截：命令未通过执行前校验，本步骤不会执行。\n"
            continue

        unmet = [d for d in step.depends_on if status.get(d) in _STOPPING_STATES]
        if unmet:
            blockers = "、".join(str(d + 1) for d in unmet)
            yield f"⏭ 跳过：依赖的第 {blockers} 步未成功完成\n\n"
            status[step.index] = _SKIPPED
            continue

        if not step.allowed:
            yield f"⛔ 已拦截（{step.blocked_reason}），未执行\n"
            yield f"$ {step.cmd}\n\n"
            status[step.index] = _BLOCKED
            continue

        if step.danger == "high":
            yield "⚠️ 高风险步骤，不自动执行。请自行审阅后手动运行：\n"
            yield f"$ {step.cmd}\n\n"
            status[step.index] = _MANUAL
            continue

        if step.check:
            yield f"🔍 检测：$ {step.check}\n"
            check_rc = None
            check_timeout = False
            check_output = []
            for chunk in _run_command(
                step.check, cwd=cwd, timeout=DEFAULT_CHECK_TIMEOUT, env=env
            ):
                if isinstance(chunk, tuple):
                    _, check_rc, check_timeout = chunk
                else:
                    check_output.append(chunk.strip())
                    yield chunk
            if check_timeout:
                status[step.index] = _TIMEOUT
                failed += 1
                yield "⏱ 检测超时，停止本步骤及其依赖步骤。\n"
                continue
            satisfied = check_rc == 0
            if re.match(r"^Test-Path\b", step.check, re.IGNORECASE):
                satisfied = satisfied and "\n".join(check_output).strip().lower() == "true"
            if satisfied:
                yield "✅ 环境检测通过，本步已满足，跳过执行\n\n"
                status[step.index] = _SATISFIED
                continue

        yield f"$ {step.cmd}\n"
        rc = None
        timed_out = False
        for chunk in _run_command(step.cmd, cwd=cwd, timeout=timeout, env=env):
            if isinstance(chunk, tuple):
                _, rc, timed_out = chunk
            else:
                yield chunk

        if rc is None:
            rc = -1
        if timed_out:
            yield f"[退出码 {rc}] ⏱ 超时结束\n\n"
            status[step.index] = _TIMEOUT
            failed += 1
        elif rc == 0:
            yield "[退出码 0 ✓]\n\n"
            status[step.index] = _OK
            ok += 1
        else:
            yield f"[退出码 {rc}] ⚠️ 本步失败\n\n"
            status[step.index] = _FAILED
            failed += 1

    yield "━━━ 完成 ━━━\n"
    unfinished = sum(state not in {_OK, _SATISFIED} for state in status.values())
    yield f"✅ 成功 {ok} | ⚠️ 失败/跳过 {unfinished} | 共 {len(plan.steps)} 步\n"
    if all(state in {_OK, _SATISFIED} for state in status.values()):
        yield "\n🎉 环境配置完成！可以开始学习了。\n"
    else:
        yield (
            "\n💡 有步骤未成功，依赖它们的步骤已跳过。常见原因："
            "① 需管理员权限；② 软件已装（检测会跳过）；③ 网络。检查上方输出后重新生成计划。\n"
        )
