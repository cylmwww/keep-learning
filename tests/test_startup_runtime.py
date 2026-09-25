import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_chroma_and_graph_defaults(tmp_path):
    code = """
import sys
from learning_ext.runtime import configure_runtime
configure_runtime()
import posthog
def reject(*args, **kwargs):
    raise AssertionError('PostHog must not be called')
posthog.capture = reject
import chromadb
from chromadb.config import Settings
assert Settings().chroma_product_telemetry_impl == 'learning_ext.telemetry.DisabledProductTelemetry'
client = chromadb.PersistentClient(path=sys.argv[1])
collection = client.get_or_create_collection('startup-regression')
collection.add(ids=['one'], embeddings=[[1.0, 0.0]], documents=['startup check'])
assert collection.get(ids=['one'])['documents'] == ['startup check']
assert collection.query(query_embeddings=[[1.0, 0.0]], n_results=1)['ids'] == [['one']]
client.delete_collection('startup-regression')
import flowsettings
assert flowsettings.GRAPHRAG_INDEX_TYPES == []
assert not any('graph' in str(item).lower() for item in flowsettings.KH_INDICES)
from learning_ext.index_manager import LearningIndexManager
from ktem.index import IndexManager
from unittest.mock import patch
manager = LearningIndexManager(None)
with patch.object(IndexManager, 'start_index', return_value='started') as start:
    for cls in ('GraphRAGIndex', 'LightRAGIndex', 'NanoGraphRAGIndex'):
        assert manager.start_index(1, 'existing', {}, 'ktem.index.file.graph.' + cls) is None
    start.assert_not_called()
    assert manager.start_index(2, 'files', {}, 'ktem.index.file.index.FileIndex') == 'started'
    assert start.call_count == 1
print('STARTUP_RUNTIME_OK')
"""
    env = os.environ.copy()
    for name in ("USE_MS_GRAPHRAG", "USE_LIGHTRAG", "USE_NANO_GRAPHRAG"):
        env.pop(name, None)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "kotaemon")])
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path / "chroma")],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "STARTUP_RUNTIME_OK" in result.stdout
    assert "Failed to send telemetry" not in result.stderr


def test_explicit_graph_opt_in(monkeypatch):
    from learning_ext.runtime import configure_runtime

    with monkeypatch.context() as context:
        context.setattr(os, "environ", os.environ.copy())
        context.setenv("USE_LIGHTRAG", "true")
        configure_runtime()
        assert os.environ["USE_LIGHTRAG"] == "true"
