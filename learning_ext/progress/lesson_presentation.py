import re


def present_lesson(node, body):
    if not re.search(r"^##\s+📌\s*本节导览", body, re.MULTILINE):
        return body
    numbers = ("一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二")
    lines = []
    fence = None
    section = 0
    introduction = False
    for line in body.splitlines():
        match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            lines.append(line)
            continue
        heading = re.match(r"^##\s+(.+)$", line) if fence is None else None
        if heading:
            title = re.sub(r"^[^\w\u4e00-\u9fff]+", "", heading.group(1)).strip()
            title = {"学习目标": "本节目标"}.get(title, title)
            introduction = title == "本节导览"
            if introduction:
                continue
            number = numbers[section] if section < len(numbers) else str(section + 1)
            line = f"## {number}、{title}"
            section += 1
        elif introduction and line.strip() == "---":
            introduction = False
        elif introduction:
            line = "> " + line
        lines.append(line)
    minutes = round(float(node.est_hours or 0) * 60)
    metadata = f"> 建议时长：{minutes} 分钟 ｜ 难度：{node.difficulty}/5"
    content = re.sub(r"\A\s*---\s*\n", "", "\n".join(lines))
    return f"# {node.code} {node.title}\n\n{metadata}\n\n" + content
