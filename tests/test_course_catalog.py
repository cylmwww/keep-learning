import json
from types import SimpleNamespace

from learning_ext.course_catalog import chapter_metadata


def test_blueprint_names_ignore_stages():
    project = SimpleNamespace(course_blueprint_json=json.dumps({"units": [
        {"title": "Java 核心", "lectures": [{"title": "面向对象", "lessons": [{"code": "1.1.1"}, {"code": "1.1.2"}]}]},
        {"title": "数据库", "lectures": [{"title": "SQL", "lessons": [{"code": "2.1.1"}]}]},
    ]}))
    result = chapter_metadata(project, [
        {"id": 1, "code": "1.1.1", "stage": "base"},
        {"id": 2, "code": "1.1.2", "stage": "sprint"},
        {"id": 3, "code": "2.1.1", "stage": "base"},
    ])
    assert result["1"] == result["2"]
    assert result["1"][1::2] == ("Java 核心", "面向对象")
    assert result["3"][1::2] == ("数据库", "SQL")


def test_old_course_groups_by_code_without_dropping_nodes():
    result = chapter_metadata(SimpleNamespace(course_blueprint_json="invalid"), [
        {"id": 1, "code": "1.1.1"}, {"id": 2, "code": "1.2.1"},
        {"id": 3, "code": "2.1"}, {"id": 4, "code": ""},
    ])
    assert result["1"][1::2] == ("第 1 章", "第 1.1 节")
    assert result["2"][1::2] == ("第 1 章", "第 1.2 节")
    assert result["3"][1::2] == ("第 2 章", "")
    assert len(result) == 4
