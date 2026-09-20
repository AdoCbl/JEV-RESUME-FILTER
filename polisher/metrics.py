"""Per-call cost and latency records for both models.

One dataclass per kind of call — :class:`RequestMetrics` for a JEV request and
:class:`LLMCallMetrics` for a writer-model completion — plus the wrapper that times a
JEV call. Aggregates and presentation live elsewhere: :mod:`polisher.report` derives the
payload and the views render it, so nothing here needs to know how a run is shown.
"""

import time
from dataclasses import dataclass
from typing import Any

from typesafe_sdk import SystemOneResponse, TypeSafeClient


@dataclass(frozen=True)
class RequestMetrics:
    """What one JEV request cost."""

    latency_ms: float
    model: str
    request_id: str
    input_tokens: int | None
    output_tokens: int | None

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "request_id": self.request_id,
            "latency_ms": round(self.latency_ms, 1),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


def _build(response: SystemOneResponse, latency_ms: float) -> RequestMetrics:
    return RequestMetrics(
        latency_ms=latency_ms,
        model=response.model,
        request_id=response.request_id,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


def timed_call(
    client: TypeSafeClient,
    state: Any,
    questions: dict,
    **kwargs: Any,
) -> tuple[SystemOneResponse, RequestMetrics]:
    """Wrap a synchronous ``system_one`` call and record what it cost."""
    started = time.perf_counter()
    response = client.system_one(state=state, questions=questions, **kwargs)
    return response, _build(response, (time.perf_counter() - started) * 1000)


@dataclass(frozen=True)
class LLMCallMetrics:
    """What one writer-model call cost."""

    latency_ms: float
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    @property
    def spend_tokens(self) -> int:
        """Tokens to bill for, treating an unreported count as zero."""
        return self.total_tokens or (self.prompt_tokens or 0) + (self.completion_tokens or 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "latency_ms": round(self.latency_ms, 1),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }
