import json


def chapter_metadata(project, nodes):
    try:
        blueprint = json.loads(getattr(project, "course_blueprint_json", "{}") or "{}")
    except (ValueError, TypeError):
        blueprint = {}
    if not isinstance(blueprint, dict):
        blueprint = {}
    names = {}
    for unit_index, unit in enumerate(blueprint.get("units", []), 1):
        for lecture_index, lecture in enumerate(unit.get("lectures", []), 1):
            for lesson in lecture.get("lessons", []):
                names[str(lesson.get("code"))] = (
                    f"unit-{unit_index}", unit.get("title") or f"第 {unit_index} 章",
                    f"lecture-{unit_index}-{lecture_index}", lecture.get("title") or f"第 {unit_index}.{lecture_index} 节",
                )
    result = {}
    for node in nodes:
        code = str(node.get("code") or "")
        parts = code.split(".")
        unit = parts[0] or "未编号"
        lecture = ".".join(parts[:2]) if len(parts) > 2 else ""
        result[str(node["id"])] = names.get(code, (
            unit, f"第 {unit} 章" if unit != "未编号" else "未编号课节",
            lecture, f"第 {lecture} 节" if lecture else "",
        ))
    return result
