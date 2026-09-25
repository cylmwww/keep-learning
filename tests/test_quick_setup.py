from types import SimpleNamespace
from unittest.mock import MagicMock
import sys

import pytest


@pytest.fixture
def setup_page(tmp_path, monkeypatch):
    from learning_ext.pages import quick_setup

    path = tmp_path / '.env'
    path.write_text('OPENAI_API_BASE=https://old.example/v1\nOPENAI_API_KEY=old-key\nOPENAI_CHAT_MODEL=old-chat\nOPENAI_EMBEDDINGS_MODEL=old-vector\nOTHER=value\n', encoding='utf-8')
    monkeypatch.setattr(quick_setup, 'ENV_FILE', path)
    monkeypatch.setattr(quick_setup, '_apply_to_runtime', MagicMock())
    return quick_setup


def test_chat_save_preserves_legacy_embedding_source(setup_page):
    result = setup_page._save_model('chat', 'chat-key', 'https://chat.example/v1', 'chat-new')
    assert '✅' in result
    cfg = setup_page._read_env()
    assert cfg['embed_base_url'] == 'https://old.example/v1'
    assert cfg['embed_api_key'] == 'old-key'
    assert cfg['embed_model'] == 'old-vector'
    assert cfg['chat_model'] == 'chat-new'
    assert 'OTHER=value' in setup_page.ENV_FILE.read_text(encoding='utf-8')
    setup_page._apply_to_runtime.assert_called_once_with('chat', 'https://chat.example/v1', 'chat-key', 'chat-new')


def test_embedding_save_does_not_change_chat(setup_page):
    assert '✅' in setup_page._save_model('embedding', 'vector-key', 'https://vector.example/v1', 'vector-new')
    cfg = setup_page._read_env()
    assert cfg['base_url'] == 'https://old.example/v1'
    assert cfg['api_key'] == 'old-key'
    assert cfg['chat_model'] == 'old-chat'
    assert cfg['embed_api_key'] == 'vector-key'
    setup_page._apply_to_runtime.assert_called_once_with('embedding', 'https://vector.example/v1', 'vector-key', 'vector-new')


def test_runtime_failure_is_reported(setup_page):
    setup_page._apply_to_runtime.side_effect = RuntimeError('private-key')
    result = setup_page._save_model('embedding', 'key', 'https://vector.example/v1', 'vector')
    assert '启用失败' in result
    assert 'private-key' not in result


def test_invalid_input_does_not_save(setup_page):
    before = setup_page.ENV_FILE.read_bytes()
    assert '❌' in setup_page._save_model('chat', 'key\nINJECT=value', 'https://chat.example/v1', 'chat')
    assert setup_page.ENV_FILE.read_bytes() == before


@pytest.mark.parametrize('kind,module,attribute', [('chat', 'ktem.llms.manager', 'llms'), ('embedding', 'ktem.embeddings.manager', 'embedding_models_manager')])
def test_runtime_updates_only_selected_manager(monkeypatch, kind, module, attribute):
    from learning_ext.pages.quick_setup import _apply_to_runtime

    manager = MagicMock()
    manager.__contains__.return_value = True
    monkeypatch.setitem(sys.modules, module, SimpleNamespace(**{attribute: manager}))
    _apply_to_runtime(kind, 'https://selected.example/v1', 'selected-key', 'selected-model')
    spec = manager.update.call_args.kwargs['spec']
    assert spec['base_url'] == 'https://selected.example/v1'
    assert spec['api_key'] == 'selected-key'
    assert spec['model'] == 'selected-model'


def test_saved_embedding_reaches_real_index_pipeline(monkeypatch):
    import ktem.embeddings.manager as module
    from ktem.index.file import pipelines
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from learning_ext.pages.quick_setup import _apply_to_runtime

    isolated_engine = create_engine('sqlite://')
    module.EmbeddingTable.__table__.create(isolated_engine)
    monkeypatch.setattr(module, 'engine', isolated_engine)
    manager = object.__new__(module.EmbeddingManager)
    manager.load()
    monkeypatch.setattr(module, 'embedding_models_manager', manager)
    monkeypatch.setattr(pipelines, 'embedding_models_manager', manager)
    for model in ('first-vector', 'updated-vector'):
        _apply_to_runtime('embedding', 'https://vector.example/v1', 'test-key', model)
        assert manager.get_default_name() == 'openai'
        for index_settings in ({}, {'embedding': 'default'}):
            pipeline = pipelines.IndexDocumentPipeline.get_pipeline({}, index_settings)
            assert pipeline.embedding is manager.get_default()
            assert pipeline.embedding.model == model
            assert pipeline.embedding.base_url == 'https://vector.example/v1'
        with Session(isolated_engine) as session:
            saved = session.get(module.EmbeddingTable, 'openai')
            assert saved.default is True
            assert saved.spec['model'] == model
        manager.load()
        assert manager.get_default().model == model
    isolated_engine.dispose()


def test_embedding_test_uses_embedding_endpoint(setup_page, monkeypatch):
    post = MagicMock(return_value=SimpleNamespace(status_code=200, json=lambda: {'data': [{'embedding': [0.1, 0.2]}]}))
    monkeypatch.setattr('requests.post', post)
    assert '2 维' in setup_page._test_embedding('https://vector.example/v1', 'vector-key', 'vector')
    assert post.call_args.args == ('https://vector.example/v1/embeddings',)
    assert post.call_args.kwargs['headers']['Authorization'] == 'Bearer vector-key'


def test_ui_registers_separate_callbacks(setup_page):
    import gradio as gr

    with gr.Blocks() as blocks:
        page = setup_page.QuickSetupPage(MagicMock())
        page.on_building_ui()
        page.on_register_events()
    chat, embedding = page.sections['chat'], page.sections['embedding']
    assert chat['key'] is not embedding['key']
    assert chat['base'] is not embedding['base']
    save_callbacks = [fn for fn in blocks.fns.values() if fn.fn.__name__ == 'save_model']
    assert len(save_callbacks) == 2
    save_callbacks[1].fn('vector-key', 'https://vector.example/v1', 'vector')
    setup_page._apply_to_runtime.assert_called_once_with('embedding', 'https://vector.example/v1', 'vector-key', 'vector')
