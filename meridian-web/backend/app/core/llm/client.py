"""OpenRouter LLM client with async streaming support."""

import logging
from typing import Optional, AsyncGenerator

import httpx
from openai import OpenAI, AsyncOpenAI

logger = logging.getLogger("meridian.llm")

# OpenRouter app-identification headers. MUST be ASCII-safe: HTTP header values
# are encoded as latin-1/ASCII, so a non-ASCII char (e.g. em-dash U+2014) raises
# at request time and silently breaks EVERY LLM call. Keep values ASCII-only.
# (Bug A — use ASCII hyphen "-", never "—".)
OPENROUTER_APP_HEADERS = {
    "HTTP-Referer": "https://github.com/meridian",
    "X-Title": "Meridian - AI Negotiation Helper",
}


# OpenRouter гео-блокирует IP прод-сервера (403 "Access denied by security policy") →
# egress через прокси в разрешённой стране, как у ElevenLabs (OPENROUTER_PROXY_URL).
# Клиенты общие на процесс, по одному на URL прокси: LLMClient создаётся на каждую
# встречу/модель/job, и свой httpx-клиент на каждый течёт соединениями.
_PROXY_TIMEOUT = httpx.Timeout(180.0, connect=15.0)
_proxied_sync: dict[str, httpx.Client] = {}
_proxied_async: dict[str, httpx.AsyncClient] = {}


def proxied_http_clients(proxy_url: str | None):
    """(sync, async) httpx-клиенты через прокси. Без прокси — (None, None)."""
    proxy = (proxy_url or "").strip()
    if not proxy:
        return None, None
    if proxy not in _proxied_sync:
        _proxied_sync[proxy] = httpx.Client(proxy=proxy, timeout=_PROXY_TIMEOUT)
    if proxy not in _proxied_async:
        _proxied_async[proxy] = httpx.AsyncClient(proxy=proxy, timeout=_PROXY_TIMEOUT)
    return _proxied_sync[proxy], _proxied_async[proxy]


class LLMClient:
    """OpenRouter API client (OpenAI-compatible)."""

    def __init__(self, api_key: str, model: str = "google/gemini-3-flash-preview",
                 temperature: float = 0.7, max_tokens: int = 300,
                 base_url: str = "https://openrouter.ai/api/v1",
                 timeout: int = 30, proxy_url: str | None = None):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

        headers = dict(OPENROUTER_APP_HEADERS)

        # Прокси берём из настроек, если явно не передан (тесты передают "").
        if proxy_url is None:
            from ...config import get_settings
            proxy_url = get_settings().openrouter_proxy_url
        sync_http, async_http = proxied_http_clients(proxy_url)
        self.proxy_enabled = sync_http is not None

        self.client = OpenAI(
            api_key=api_key, base_url=base_url, default_headers=headers,
            **({"http_client": sync_http} if sync_http else {}),
        )
        self.async_client = AsyncOpenAI(
            api_key=api_key, base_url=base_url, default_headers=headers,
            **({"http_client": async_http} if async_http else {}),
        )
        # Default system prompt; overridden by set_system_prompt()
        from .prompts import PromptBuilder
        self.system_prompt = PromptBuilder().system_prompt

    def set_system_prompt(self, prompt: str):
        """Set custom system prompt (e.g. from role data)."""
        self.system_prompt = prompt

    def get_suggestion(self, prompt: str,
                       max_tokens: Optional[int] = None) -> Optional[str]:
        """Get AI suggestion (non-streaming, sync)."""
        max_tokens = max_tokens or self.max_tokens
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=max_tokens,
                temperature=self.temperature,
                timeout=self.timeout
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error("LLM error: %s", e)
            return None

    async def get_suggestion_async(self, prompt: str,
                                    max_tokens: Optional[int] = None) -> Optional[str]:
        """Get AI suggestion (non-streaming, async)."""
        max_tokens = max_tokens or self.max_tokens
        try:
            response = await self.async_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=max_tokens,
                temperature=self.temperature,
                timeout=self.timeout
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error("LLM async error: %s", e)
            return None

    async def get_suggestion_streaming_async(
        self, prompt: str, max_tokens: Optional[int] = None
    ) -> AsyncGenerator[str, None]:
        """Get AI suggestion with streaming (async generator yielding accumulated text)."""
        max_tokens = max_tokens or self.max_tokens
        try:
            stream = await self.async_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=max_tokens,
                temperature=self.temperature,
                timeout=self.timeout,
                stream=True
            )

            full_response = ""
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    full_response += chunk.choices[0].delta.content
                    yield full_response

        except Exception as e:
            logger.error("LLM streaming error: %s", e)
