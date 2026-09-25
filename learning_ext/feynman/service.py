"""费曼对话 + 苏格拉底引导。

两种增强对话模式：
    - 费曼模式：AI 扮演小白，引导用户讲解，通过提问暴露理解漏洞
    - 苏格拉底模式：不给答案，反问引导用户自己推导
"""

from __future__ import annotations

from typing import Iterator, Optional

from learning_ext.llm import chat


FEYNMAN_SYSTEM = """你在费曼对话模式中扮演一个"想学但什么都不懂的小白"。
用户正在学习某个知识点，他需要用最通俗的语言向你解释这个概念。

你的职责：
1. 认真听用户的解释
2. 用外行人的视角提出疑问，专挑用户解释不清楚、跳跃、或自相矛盾的地方
3. 不直接给答案，而是追问"这里为什么？"、"我没听懂 XX，能再说说吗？"
4. 当用户解释到位时，给予肯定；当发现概念性错误时，指出矛盾让用户自纠
5. 每次只回应 2-4 句，保持对话节奏

语气：好奇、真诚、有点笨但不傻，像一个聪明但完全没基础的朋友。"""

SOCRATES_SYSTEM = """你在苏格拉底模式中是一位启发式导师。
用户在学习，但你不直接给答案，而是通过精心设计的提问引导用户自己发现答案。

规则：
1. 绝不直接给出最终答案或结论
2. 每次用一个引导性问题推进
3. 问题要基于用户当前的回答层层深入
4. 当用户走偏时，用反例或边界情况提醒
5. 当用户推导正确时，用下一个问题确认并推进
6. 每次只问 1-2 个问题，3 句话以内"""


def feynman_chat(
    node_title: str,
    node_description: str,
    user_message: str,
    history: list[dict] | None = None,
    *,
    model_name: Optional[str] = None,
) -> str:
    """费曼对话单轮。

    Args:
        node_title: 当前知识点标题
        node_description: 知识点说明 (AI 据此判断用户解释是否到位)
        user_message: 用户本轮的讲解
        history: 对话历史 [{"role":"user|assistant","content":"..."}]
    """
    context = f"【当前知识点】{node_title}\n【知识点正确定义】{node_description}\n"
    context += "(注意：以上是供你参考的标准内容，用户正在尝试向你解释，你要据此判断他解释得对不对，但不要直接复述)\n\n"

    if history:
        context += "【之前的对话】\n"
        for h in history[-6:]:
            role = "用户" if h["role"] == "user" else "你"
            context += f"{role}: {h['content']}\n"
        context += "\n"

    context += f"【用户最新解释】{user_message}\n\n请以小白的身份回应。"

    return chat(context, system=FEYNMAN_SYSTEM, model_name=model_name, temperature=0.6)


def socrates_chat(
    node_title: str,
    node_description: str,
    user_message: str,
    history: list[dict] | None = None,
    *,
    model_name: Optional[str] = None,
) -> str:
    """苏格拉底引导单轮。"""
    context = f"【学习主题】{node_title}\n【学习目标】{node_description}\n\n"
    if history:
        context += "【对话历史】\n"
        for h in history[-6:]:
            role = "用户" if h["role"] == "user" else "导师"
            context += f"{role}: {h['content']}\n"
        context += "\n"
    context += f"【用户】{user_message}\n\n请用一个问题引导。"

    return chat(context, system=SOCRATES_SYSTEM, model_name=model_name, temperature=0.4)
