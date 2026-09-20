import time
from dataclasses import dataclass
from typing import Any

from typesafe_sdk import AsyncTypeSafeClient, SystemOneResponse, TypeSafeClient


@dataclass
class RequestMetrics:
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

    def report(self) -> None:
        def fmt(n: int | None) -> str:
            return f"{n:,}" if n is not None else "n/a"

        print("── Request metrics ────────────────────────────────────────────")
        print(f"  Model:         {self.model}")
        print(f"  Request ID:    {self.request_id}")
        print(f"  Latency:       {self.latency_ms:.0f} ms")
        print(f"  Input tokens:  {fmt(self.input_tokens)}")
        print(f"  Output tokens: {fmt(self.output_tokens)}")
        print(f"  Total tokens:  {fmt(self.total_tokens)}")


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
    """Wraps a synchronous system_one call and returns timing + token metrics."""
    t0 = time.perf_counter()
    response = client.system_one(state=state, questions=questions, **kwargs)
    return response, _build(response, (time.perf_counter() - t0) * 1000)


async def async_timed_call(
    client: AsyncTypeSafeClient,
    state: Any,
    questions: dict,
    **kwargs: Any,
) -> tuple[SystemOneResponse, RequestMetrics]:
    """Async version of timed_call for use with AsyncTypeSafeClient."""
    t0 = time.perf_counter()
    response = await client.system_one(state=state, questions=questions, **kwargs)
    return response, _build(response, (time.perf_counter() - t0) * 1000)
