"""An LLM client bound to a *task*, not to a server: every call goes through the
ModelHost, which makes sure the right model is the one resident."""
from __future__ import annotations

from typing import Any

from agency.llm.client import ChatResult, LLMError, LocalLLM, Message
from agency.models.host import ModelHost
from agency.models.registry import ModelSpec


class HostedLLM:
    def __init__(self, host: ModelHost, spec: ModelSpec, *, thinking_effort: str = "xhigh", fallback: ModelSpec | None = None, timeout: float = 1800.0):
        self.host, self.spec, self.fallback, self.timeout = host, spec, fallback, timeout
        self.thinking_effort = thinking_effort
        self._client: LocalLLM | None = None
        self._client_spec: ModelSpec | None = None
        self.failed_over = False

    @property
    def model(self) -> ModelSpec:
        return self._client_spec or self.spec

    def _client_for(self, spec: ModelSpec) -> LocalLLM:
        ep = self.host.activate(spec)
        if self._client is None or self._client_spec is None or self._client_spec.id != spec.id or self._client.base_url != ep.base_url.rstrip("/"):
            self._client = LocalLLM(ep.base_url, spec, timeout=self.timeout)
            self._client_spec = spec
        return self._client

    def _call(self, fn: str, *args: Any, **kw: Any) -> Any:
        spec = self.fallback if (self.failed_over and self.fallback) else self.spec
        try:
            return getattr(self._client_for(spec), fn)(*args, **kw)
        except Exception as e:  # noqa: BLE001
            if self.fallback and not self.failed_over:
                self.failed_over = True
                self.host.on_event({"kind": "brain.failover", "model": self.fallback.name, "reason": str(e)[:200], "memory_gb": self.fallback.memory_gb})
                return getattr(self._client_for(self.fallback), fn)(*args, **kw)
            raise

    # same surface as LocalLLM
    def chat(self, messages: list[Message], **kw: Any) -> ChatResult:
        kw.setdefault("extra", {})
        return self._call("chat", messages, **_with_effort(kw, self.thinking_effort))

    def complete_json(self, system: str, user: str, **kw: Any) -> Any:
        return self._call("complete_json", system, user, **kw)

    def embed(self, texts: list[str], model_id: str | None = None) -> list[list[float]]:
        return self._call("embed", texts, model_id or self.spec.id)

    def describe_image(self, image_b64: str, question: str, mime: str = "image/png") -> str:
        return self._call("describe_image", image_b64, question, mime)


def _with_effort(kw: dict[str, Any], effort: str) -> dict[str, Any]:
    kw.pop("extra", None)
    return kw
