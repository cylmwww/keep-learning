import json
import re
from pathlib import Path

import gradio as gr


TEXT = {
    "Conversations": "对话列表",
    "Chat sessions": "历史对话",
    "Browse conversation": "选择历史对话",
    "Suggest chat": "推荐提问",
    "Share this conversation": "分享此对话",
    "Conversation name": "对话名称",
    "(Enter) to save": "按回车保存",
    "New chat": "新建对话",
    "File Collection": "文件资料库",
    "GraphRAG Collection": "GraphRAG 资料库",
    "LightRAG Collection": "LightRAG 资料库",
    "Search All": "检索全部资料",
    "Search In File(s)": "检索指定文件",
    "Quick Upload": "快速上传",
    "Or paste URLs": "或粘贴网页链接",
    "Chat Suggestion": "推荐提问",
    "Next Question": "下一条问题",
    "Feedback": "问题反馈",
    "Correctness:": "回答是否正确：",
    "Other issue:": "其他问题：",
    "The answer is correct": "回答正确",
    "The answer is incorrect": "回答不正确",
    "The answer is offensive": "回答包含冒犯性内容",
    "The evidence is incorrect": "引用依据不正确",
    "More detail (e.g. how wrong is it, what is the correct answer, etc...)": "补充说明（例如：哪里有误、正确答案是什么等）",
    "This will send the current chat and the user settings to help with investigation": "提交时会附上当前对话和用户设置，以帮助排查问题。",
    "Report": "提交反馈",
    "Chat settings": "问答设置",
    "Reasoning method": "推理方式",
    "Model": "模型",
    "Language": "回答语言",
    "Simple QA": "基础问答",
    "Complex QA": "复杂问答",
    "simple": "基础问答",
    "complex": "复杂问答",
    "ReAct": "ReAct 推理",
    "ReWOO": "ReWOO 推理",
    "ReAct Agent": "ReAct 智能体",
    "ReWOO Agent": "ReWOO 智能体",
    "(default)": "默认",
    "English": "英语",
    "Chinese": "中文",
    "Japanese": "日语",
    "Vietnamese": "越南语",
    "French": "法语",
    "German": "德语",
    "Spanish": "西班牙语",
    "Italian": "意大利语",
    "Portuguese": "葡萄牙语",
    "Russian": "俄语",
    "Arabic": "阿拉伯语",
    "Korean": "韩语",
    "Hindi": "印地语",
    "Bengali": "孟加拉语",
    "Punjabi": "旁遮普语",
    "Dutch": "荷兰语",
    "Turkish": "土耳其语",
    "Polish": "波兰语",
    "Ukrainian": "乌克兰语",
    "Romanian": "罗马尼亚语",
    "Greek": "希腊语",
    "Hungarian": "匈牙利语",
    "Swedish": "瑞典语",
    "Czech": "捷克语",
    "Finnish": "芬兰语",
    "Danish": "丹麦语",
    "Norwegian": "挪威语",
    "Hebrew": "希伯来语",
    "Thai": "泰语",
    "Indonesian": "印尼语",
    "Malay": "马来语",
    "citation: highlight": "引用：高亮显示",
    "citation: inline": "引用：行内标注",
    "no citation": "不显示引用",
    "Mindmap (on)": "思维导图（开启）",
    "Mindmap (off)": "思维导图（关闭）",
    "Information panel": "参考信息",
    "This is the beginning of a new conversation.\nStart by uploading a file or a web URL. Visit Files tab for more options (e.g: GraphRAG).": "开始一段新对话。\n上传文件或粘贴网页链接即可开始。在「资料库」中可使用更多功能（如 GraphRAG）。",
    "Type a message, use @WebSearch, or tag a file with @filename": "输入问题，使用 @WebSearch 搜索网页，或用 @文件名 引用文件",
    "Directory upload": "上传文件夹",
    "Directory path...": "输入文件夹路径…",
    "Advanced indexing options": "高级索引选项",
    "Force reindex file": "强制重新建立索引",
    "Upload and Index": "上传并建立索引",
    "Upload Files": "上传文件",
    "Use Web Links": "使用网页链接",
    "Input web URLs": "输入网页链接",
    "(separated by new line)": "每行输入一个链接",
    "Upload Progress": "上传进度",
    "Upload result": "上传结果",
    "Upload info": "上传详情",
    "Clear Upload Info and Close": "清空上传信息并关闭",
    "Files": "文件",
    "File": "文件",
    "Groups": "文件分组",
    "Filter by name:": "按文件名筛选：",
    "(1) Case-insensitive. (2) Search with empty string to show all files.": "不区分大小写；留空可显示全部文件。",
    "Go to Chat": "前往知识问答",
    "Download": "下载",
    "Start download": "开始下载",
    "Download all files": "下载全部文件",
    "Delete all files": "删除全部文件",
    "Confirm delete": "确认删除",
    "Delete": "删除",
    "Cancel": "取消",
    "Close": "关闭",
    "Add": "新增分组",
    "Save": "保存",
    "Advance options": "高级选项",
    "Group name": "分组名称",
    "Attached files": "关联文件",
    "Add new group": "新增分组",
    "Group Information": "分组信息",
    "Selected file: (please select above)": "已选文件：（请在上方选择）",
    "Chunk type": "内容片段类型",
    "all": "全部",
    "text": "文本",
    "table": "表格",
    "image": "图片",
    "thumbnail": "缩略图",
    "id": "编号",
    "name": "名称",
    "size": "大小",
    "tokens": "词元数",
    "loader": "解析器",
    "date_created": "创建时间",
    "files": "文件",
}


def translate(value):
    if not isinstance(value, str):
        return value
    if value in TEXT:
        return TEXT[value]
    if value.startswith("#"):
        prefix, _, title = value.partition(" ")
        return prefix + " " + TEXT.get(title, title)
    value = re.sub(r"(?m)^(\s*-?\s*)Supported file types: ", r"\1支持的文件类型：", value)
    value = re.sub(r"(?m)^(\s*-?\s*)Maximum file size: ", r"\1单个文件大小上限：", value)
    return re.sub(r"The index can have maximum (\d+) files", r"资料库最多可包含 \1 个文件", value)


def localize_pages(app):
    roots = [app._tabs["chat-tab"]]
    roots.extend(tab for tab in app._tabs.values() if tab.elem_id == "indices-tab")
    dynamic = []

    def visit(component):
        if isinstance(component, gr.File) and component.label is None:
            component.label = "文件"
        for attr in ("label", "info", "placeholder"):
            if hasattr(component, attr):
                setattr(component, attr, translate(getattr(component, attr)))
        if isinstance(component, (gr.Button, gr.Markdown, gr.HTML)):
            component.value = translate(component.value)
        if isinstance(component, (gr.Dropdown, gr.Radio, gr.CheckboxGroup)):
            if component is app.chat_page.model_type:
                component.choices = [("默认" if label == "(default)" else label, value) for label, value in component.choices]
            else:
                component.choices = [(translate(label), value) for label, value in component.choices]
        for child in getattr(component, "children", []):
            visit(child)

    for root in roots:
        visit(root)
    app.chat_page.chat_panel.text_input.label = "输入问题"
    app.chat_page.quick_urls.label = "网页链接"
    app.chat_page.reasoning_type.label = "推理方式"
    app.chat_page.model_type.label = "模型"
    app.chat_page.language.label = "回答语言"
    app.chat_page.citation.label = "引用方式"
    for index in app.index_manager.indices:
        page = getattr(app, f"_index_{index.id}", None)
        if hasattr(page, "selected_panel_false"):
            page.selected_panel_false = "已选文件：（请在上方选择）"
            page.selected_panel_true = "已选文件：{name}"
            for attr in ("group_label", "chunk_header"):
                component = getattr(page, attr)
                dynamic.append(component.elem_id or f"component-{component._id}")

    script = Path(__file__).with_name("assets").joinpath("localization.js").read_text(encoding="utf-8")
    return script.replace("__TRANSLATIONS__", json.dumps(TEXT, ensure_ascii=False)).replace(
        "__DYNAMIC_IDS__", json.dumps(dynamic)
    )
