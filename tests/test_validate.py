"""LLM 输出严格校验的单元测试。

重点是文档里点名的那类缺陷：``bool("false")`` 为真，
以及 ``"3"`` / ``True`` 这类偷渡成数字的值。
"""

from __future__ import annotations

import pytest

from learning_ext.llm.validate import (
    LLMOutputError,
    as_str,
    require_bool,
    require_dict,
    require_enum,
    require_int,
    require_list,
    require_number,
    require_str,
    require_str_list,
)


class TestTheBoolTrap:
    """模型返回字符串 "false" 时不能被当成真。"""

    def test_nonempty_string_is_truthy_in_python(self):
        assert bool("false") is True  # 这就是必须校验的原因

    @pytest.mark.parametrize("value", ["false", "true", "0", "", 0, 1, None])
    def test_strings_and_numbers_are_rejected(self, value):
        with pytest.raises(LLMOutputError, match="boolean"):
            require_bool(value, "is_correct")

    @pytest.mark.parametrize("value", [True, False])
    def test_real_booleans_pass(self, value):
        assert require_bool(value, "is_correct") is value


class TestNumbers:
    @pytest.mark.parametrize("value", ["0.9", "1", None, [], {}])
    def test_numeric_strings_rejected(self, value):
        with pytest.raises(LLMOutputError, match="number"):
            require_number(value, "score")

    @pytest.mark.parametrize("value", [True, False])
    def test_bool_is_not_a_number(self, value):
        with pytest.raises(LLMOutputError, match="number"):
            require_number(value, "score")

    def test_int_is_accepted_as_number(self):
        assert require_number(1, "score") == 1.0

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_rejected(self, value):
        with pytest.raises(LLMOutputError, match="有限"):
            require_number(value, "score")

    def test_bounds(self):
        with pytest.raises(LLMOutputError, match="下限"):
            require_number(-0.1, "score", min_value=0.0)
        with pytest.raises(LLMOutputError, match="上限"):
            require_number(1.5, "score", max_value=1.0)
        assert require_number(0.5, "score", min_value=0.0, max_value=1.0) == 0.5


class TestIntegers:
    @pytest.mark.parametrize("value", ["3", 3.0, None, True, False])
    def test_non_int_rejected(self, value):
        with pytest.raises(LLMOutputError, match="integer"):
            require_int(value, "difficulty")

    def test_bounds(self):
        with pytest.raises(LLMOutputError, match="下限"):
            require_int(0, "difficulty", min_value=1)
        with pytest.raises(LLMOutputError, match="上限"):
            require_int(6, "difficulty", max_value=5)
        assert require_int(3, "difficulty", min_value=1, max_value=5) == 3


class TestStrings:
    @pytest.mark.parametrize("value", [3, None, [], {}])
    def test_non_str_rejected(self, value):
        with pytest.raises(LLMOutputError, match="string"):
            require_str(value, "stem")

    def test_empty_rejected_unless_allowed(self):
        with pytest.raises(LLMOutputError, match="不能为空"):
            require_str("   ", "stem")
        assert require_str("   ", "stem", allow_empty=True) == ""

    def test_whitespace_is_stripped(self):
        assert require_str("  abc  ", "stem") == "abc"

    def test_max_len_truncates(self):
        assert require_str("abcdef", "stem", max_len=3) == "abc"

    def test_as_str_defaults_only_on_none(self):
        assert as_str(None, "explanation") == ""
        assert as_str(None, "explanation", default="无") == "无"
        assert as_str("", "explanation", default="无") == ""
        with pytest.raises(LLMOutputError, match="string"):
            as_str(3, "explanation")


class TestEnums:
    def test_valid_value_passes(self):
        assert require_enum("short", "qtype", ("choice", "short")) == "short"

    @pytest.mark.parametrize("value", ["essay", "", None, 3, True])
    def test_invalid_value_rejected(self, value):
        with pytest.raises(LLMOutputError):
            require_enum(value, "qtype", ("choice", "short"))

    def test_error_message_lists_allowed_values(self):
        with pytest.raises(LLMOutputError, match="choice"):
            require_enum("essay", "qtype", ("choice", "short"))


class TestContainers:
    def test_dict_and_list(self):
        assert require_dict({"a": 1}, "root") == {"a": 1}
        assert require_list([1], "root") == [1]
        with pytest.raises(LLMOutputError, match="object"):
            require_dict([], "root")
        with pytest.raises(LLMOutputError, match="array"):
            require_list({}, "root")

    def test_str_list_rejects_non_string_items(self):
        with pytest.raises(LLMOutputError, match=r"missed_points\[1\]"):
            require_str_list(["ok", 3], "missed_points")

    def test_str_list_min_items(self):
        with pytest.raises(LLMOutputError, match="至少需要"):
            require_str_list([], "options", min_items=2)
        assert require_str_list(["A", "B"], "options", min_items=2) == ["A", "B"]

    def test_str_list_max_items_truncates(self):
        assert require_str_list(["A", "B", "C"], "options", max_items=2) == ["A", "B"]


def test_error_is_a_value_error_so_callers_can_catch_broadly():
    assert issubclass(LLMOutputError, ValueError)
