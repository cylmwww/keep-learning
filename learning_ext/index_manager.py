import logging

from ktem.index import IndexManager
from theflow.settings import settings


class LearningIndexManager(IndexManager):
    def start_index(self, id, name, config, index_type):
        flags = {
            "GraphRAGIndex": "USE_MS_GRAPHRAG",
            "LightRAGIndex": "USE_LIGHTRAG",
            "NanoGraphRAGIndex": "USE_NANO_GRAPHRAG",
        }
        flag = flags.get(index_type.rsplit(".", 1)[-1])
        if index_type.startswith("ktem.index.file.graph.") and flag:
            if not getattr(settings, flag, False):
                logging.getLogger(__name__).info("跳过已禁用的图谱索引: %s", name)
                return None
        return super().start_index(id, name, config, index_type)
