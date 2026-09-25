"""LLM 输出的严格类型校验。

LLM 返回的 JSON 字段类型不可信：
    - 字符串 "false" 在 ``bool()`` 下为真，会把答错静默记成答对；
    - "3" 这类数字字符串会静默参与算术，也会绕过枚举检查；
    - ``True`` 是 ``int`` 的子类，直接 ``isinstance(x, int)`` 挡不住。

所有 LLM 输出在入库前一律经这里校验，类型不符直接拒绝，不做隐式转换。
调用方决定拒绝的粒度：整批拒绝（抛错）还是丢弃单条（捕获 :class:`LLMOutputError`）。
"""

from __future__ import annotations

from typing import Any, Optional, Sequence


class LLMOutputError(ValueError):
    """LLM 输出不符合预期 schema。"""


def _fail(field: str, expected: str, value: Any) -> LLMOutputError:
    return LLMOutputError(
        f"字段 `{field}` 类型错误：期望 {expected}，实际 {type(value).__name__}"
        f"（值 {value!r}）"
    )


def require_dict(value: Any, field: str = "<root>") -> dict:
    if not isinstance(value, dict):
        raise _fail(field, "object", value)
    return value


def require_list(value: Any, field: str = "<root>") -> list:
    if not isinstance(value, list):
        raise _fail(field, "array", value)
    return value


def require_str(
    value: Any,
    field: str,
    *,
    allow_empty: bool = False,
    max_len: Optional[int] = None,
) -> str:
    if not isinstance(value, str):
        raise _fail(field, "string", value)
    out = value.strip()
    if not out and not allow_empty:
        raise LLMOutputError(f"字段 `{field}` 不能为空")
    if max_len is not None:
        out = out[:max_len]
    return out


def as_str(value: Any, field: str, *, default: str = "", max_len: Optional[int] = None) -> str:
    """字段缺失（None）时用 default，出现但类型错误则抛错。"""
    if value is None:
        return default
    return require_str(value, field, allow_empty=True, max_len=max_len)


def require_bool(value: Any, field: str) -> bool:
    """只接受真正的 JSON 布尔值。字符串 "false" / "true" 一律拒绝。"""
    if isinstance(value, bool):
        return value
    raise _fail(field, "boolean", value)


def require_int(
    value: Any,
    field: str,
    *,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
) -> int:
    # bool 是 int 子类, 必须显式排除, 否则 True 会被当成 1
    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(field, "integer", value)
    if min_value is not None and value < min_value:
        raise LLMOutputError(f"字段 `{field}` 小于下限 {min_value}：{value}")
    if max_value is not None and value > max_value:
        raise LLMOutputError(f"字段 `{field}` 大于上限 {max_value}：{value}")
    return value


def require_number(
    value: Any,
    field: str,
    *,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _fail(field, "number", value)
    out = float(value)
    if out != out or out in (float("inf"), float("-inf")):
        raise LLMOutputError(f"字段 `{field}` 不是有限数字：{value!r}")
    if min_value is not None and out < min_value:
        raise LLMOutputError(f"字段 `{field}` 小于下限 {min_value}：{out}")
    if max_value is not None and out > max_value:
        raise LLMOutputError(f"字段 `{field}` 大于上限 {max_value}：{out}")
    return out


def require_enum(value: Any, field: str, allowed: Sequence[str]) -> str:
    out = require_str(value, field)
    if out not in allowed:
        raise LLMOutputError(
            f"字段 `{field}` 取值非法：{out!r}，允许 {list(allowed)}"
        )
    return out


def require_str_list(
    value: Any,
    field: str,
    *,
    min_items: int = 0,
    max_items: Optional[int] = None,
) -> list[str]:
    raw = require_list(value, field)
    out = [require_str(item, f"{field}[{i}]") for i, item in enumerate(raw)]
    if len(out) < min_items:
        raise LLMOutputError(f"字段 `{field}` 至少需要 {min_items} 项，实际 {len(out)}")
    if max_items is not None:
        out = out[:max_items]
    return out
