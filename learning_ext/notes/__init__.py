"""学习笔记与参考资料模块。"""

from learning_ext.notes.service import (
    explain_term,
    fetch_preview,
    generate_resources,
    get_note,
    get_resources,
    save_note,
    save_resources_to_db,
)

__all__ = [
    "get_note",
    "save_note",
    "get_resources",
    "generate_resources",
    "save_resources_to_db",
    "fetch_preview",
    "explain_term",
]
