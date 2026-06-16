"""OpenRouter LLM client with async streaming support."""

from typing import Optional, Callable, AsyncGenerator

from openai import OpenAI, AsyncOpenAI

# OpenRouter app-identification headers. MUST be ASCII-safe: HTTP header values
# are encoded as latin-1/ASCII, so a non-ASCII char (e.g. em-dash U+2014) raises
# at request time and silently breaks EVERY LLM call. Keep values ASCII-only.
# (Bug A — use ASCII hyphen "-", never "—".)
OPENROUTER_APP_HEADERS = {
    "HTTP-Referer": "https://github.com/meridian",
    "X-Title": "Meridian - AI Negotiation Helper",
}


class LLMClient:
    """OpenRouter API client (OpenAI-compatible)."""

    def __init__(self, api_key: str, model: str = "google/gemini-3-flash-preview",
                 temperature: float = 0.7, max_tokens: int = 300,
                 base_url: str = "https://openrouter.ai/api/v1",
                 timeout: int = 30):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

        headers = dict(OPENROUTER_APP_HEADERS)

        self.client = OpenAI(
            api_key=api_key, base_url=base_url, default_headers=headers
        )
        self.async_client = AsyncOpenAI(
            api_key=api_key, base_url=base_url, default_headers=headers
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
            print(f"LLM error: {e}")
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
            print(f"LLM async error: {e}")
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
            print(f"LLM streaming error: {e}")
