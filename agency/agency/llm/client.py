"""Chat client for the local director/worker model (LM Studio, Ollama, mlx-lm server:
anything that speaks the OpenAI chat-completions protocol) plus an optional
Anthropic path that is only used when ``director.provider == "anthropic"``.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from agency.models.registry import ModelSpec

JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.S)


class LLMError(RuntimeError):
    pass


@dataclass
class Message:
    role: str
    content: str | list[dict[str, Any]]

    def dump(self) -> dict[str, Any]:
        return {"role": self.role, "content": self.content}


@dataclass
class ChatResult:
    text: str
    raw: dict[str, Any] = field(default_factory=dict)

    def json(self) -> Any:
        return extract_json(self.text)


def extract_json(text: str) -> Any:
    """Pull the first JSON object/array out of a model reply, tolerant of fences and chatter."""
    text = text.strip()
    # Strip <think>...</think> blocks some reasoning models emit.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = JSON_BLOCK.search(text)
    if m:
        return json.loads(m.group(1))
    # Last resort: first balanced {...} or [...]
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == opener:
                depth += 1
            elif text[i] == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise LLMError(f"no JSON found in model reply: {text[:200]!r}")


class LocalLLM:
    """OpenAI-compatible chat against a local server (default: LM Studio on :1234)."""

    def __init__(self, base_url: str, model: ModelSpec, timeout: float = 600.0, transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport)

    def chat(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
        schema: dict[str, Any] | None = None,
    ) -> ChatResult:
        body: dict[str, Any] = {
            "model": self.model.id,
            "messages": [m.dump() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "reply", "schema": schema}}
        elif json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            r = self.client.post("/v1/chat/completions", json=body)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(f"local model call failed ({self.model.name} @ {self.base_url}): {e}") from e
        data = r.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"unexpected reply shape: {data}") from e
        return ChatResult(text=text or "", raw=data)

    def complete_json(self, system: str, user: str, *, schema: dict[str, Any] | None = None, temperature: float = 0.4, retries: int = 2) -> Any:
        messages = [Message("system", system), Message("user", user)]
        last: Exception | None = None
        for attempt in range(retries + 1):
            result = self.chat(messages, temperature=temperature, json_mode=True, schema=schema)
            try:
                return result.json()
            except (LLMError, json.JSONDecodeError) as e:
                last = e
                messages.append(Message("assistant", result.text))
                messages.append(Message("user", "That was not valid JSON. Reply with only the JSON object, nothing else."))
        raise LLMError(f"model never produced valid JSON: {last}")

    def embed(self, texts: list[str], model_id: str) -> list[list[float]]:
        r = self.client.post("/v1/embeddings", json={"model": model_id, "input": texts})
        r.raise_for_status()
        data = r.json()["data"]
        return [row["embedding"] for row in sorted(data, key=lambda d: d["index"])]

    def describe_image(self, image_b64: str, question: str, mime: str = "image/png") -> str:
        msg = Message(
            "user",
            [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
            ],
        )
        return self.chat([msg], temperature=0.2, max_tokens=800).text


class AnthropicLLM:
    """Optional paid director. Only constructed when the user flips director.provider to 'anthropic'."""

    def __init__(self, model: str, api_key: str | None = None, timeout: float = 600.0):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set; the paid director cannot start")
        self.client = httpx.Client(base_url="https://api.anthropic.com", timeout=timeout)

    def chat(self, messages: list[Message], *, temperature: float = 0.7, max_tokens: int = 4096, json_mode: bool = False, schema: dict[str, Any] | None = None) -> ChatResult:
        system = "\n".join(m.content for m in messages if m.role == "system" and isinstance(m.content, str))
        convo = [m.dump() for m in messages if m.role != "system"]
        if json_mode or schema:
            system += "\nReply with a single JSON object and nothing else."
        r = self.client.post(
            "/v1/messages",
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            json={"model": self.model, "max_tokens": max_tokens, "temperature": temperature, "system": system, "messages": convo},
        )
        r.raise_for_status()
        data = r.json()
        text = "".join(block.get("text", "") for block in data.get("content", []))
        return ChatResult(text=text, raw=data)

    complete_json = LocalLLM.complete_json  # same algorithm, different transport

    def embed(self, texts: list[str], model_id: str) -> list[list[float]]:
        raise LLMError("embeddings always run on the local model")

    def describe_image(self, image_b64: str, question: str, mime: str = "image/png") -> str:
        raise LLMError("vision runs on the local model")
