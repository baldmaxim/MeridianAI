"""Egress LLM через прокси (OPENROUTER_PROXY_URL).

OpenRouter гео-блокирует IP прод-сервера: прямой запрос → 403 «Access denied by security
policy». Прокси уже применялся в генераторе протокола, но НЕ в LLMClient, через который
идут живые подсказки, Signal Engine, дерево общения и извлечение знаний.
"""

import httpx
import pytest

from app.core.llm import client as llm_client_mod
from app.core.llm.client import LLMClient, proxied_http_clients


@pytest.fixture(autouse=True)
def _clean_client_cache():
    llm_client_mod._proxied_sync.clear()
    llm_client_mod._proxied_async.clear()
    yield
    for c in llm_client_mod._proxied_sync.values():
        c.close()
    llm_client_mod._proxied_sync.clear()
    llm_client_mod._proxied_async.clear()


@pytest.mark.parametrize("empty", ["", "   ", None])
def test_no_proxy_configured_means_direct_calls(empty):
    assert proxied_http_clients(empty) == (None, None)


def test_proxy_clients_are_built_for_both_transports():
    sync_c, async_c = proxied_http_clients("http://proxy.local:3128")
    assert isinstance(sync_c, httpx.Client)
    assert isinstance(async_c, httpx.AsyncClient)


def test_clients_are_shared_per_proxy_url():
    """LLMClient создаётся на каждую встречу/модель/job — свой httpx на каждый бы тёк."""
    a = proxied_http_clients("http://proxy.local:3128")
    b = proxied_http_clients("http://proxy.local:3128")
    assert a[0] is b[0] and a[1] is b[1]
    other = proxied_http_clients("http://other.local:3128")
    assert other[0] is not a[0]


def test_llm_client_routes_through_proxy_when_configured():
    c = LLMClient(api_key="test-key", proxy_url="http://proxy.local:3128")
    assert c.proxy_enabled is True
    assert c.async_client._client is llm_client_mod._proxied_async["http://proxy.local:3128"]


def test_llm_client_goes_direct_without_proxy():
    c = LLMClient(api_key="test-key", proxy_url="")
    assert c.proxy_enabled is False


def test_proxy_is_read_from_settings_by_default(monkeypatch):
    from app.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("OPENROUTER_PROXY_URL", "http://from-settings.local:3128")
    try:
        c = LLMClient(api_key="test-key")
        assert c.proxy_enabled is True
    finally:
        get_settings.cache_clear()
