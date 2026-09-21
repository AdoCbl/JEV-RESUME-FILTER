"""Shared fixtures and stub factories for all tests.

Tests use fake clients (answer stubs) so no API keys or network access are needed.
"""

from __future__ import annotations

from typing import Any

# ── Fake TypeSafe response objects ───────────────────────────────────────────


class FakeScore:
    def __init__(self, score: float = 3.0, confidence: float = 0.9) -> None:
        self.score = score
        self.confidence = confidence
        self.probabilities = {str(i): (1.0 if i == round(score) else 0.0) for i in range(5)}


class FakeNoul:
    def __init__(self, noul: float = 0.1) -> None:
        self.noul = noul


class FakeChoice:
    def __init__(self, choice: str = "jd_alignment", confidence: float = 0.8) -> None:
        self.choice = choice
        self.confidence = confidence
        self.probabilities = {choice: confidence}


class FakeAnswers:
    def __init__(self, answers: dict[str, Any]) -> None:
        self._answers = answers

    def __getitem__(self, key: str) -> Any:
        return self._answers[key]


class FakeResponse:
    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = FakeAnswers(answers)
        self.model = "fake-model"
        self.request_id = "fake-req-001"

        class FakeUsage:
            input_tokens = 100
            output_tokens = 50

        self.usage = FakeUsage()


def make_review_answers(n_lines: int = 3) -> dict[str, Any]:
    """Build a complete fake answer dict for n_lines audited lines.

    Line support is 0.9 (well-grounded) and guardrails are 0.05 (no fabrication).
    """
    from polisher.judge import DIMENSIONS, GUARDRAILS

    answers: dict[str, Any] = {}
    for name in DIMENSIONS:
        answers[name] = FakeScore()
    for name in GUARDRAILS:
        answers[name] = FakeNoul(0.05)  # low probability of fabrication = clean draft
    answers["biggest_gap"] = FakeChoice()
    for i in range(n_lines):
        answers[f"line_{i:02d}"] = FakeNoul(0.9)  # high probability of being supported
    return answers


class FakeTypeSafeClient:
    """A TypeSafeClient stub that returns a fixed response without any network call."""

    def __init__(self, answers: dict[str, Any] | None = None, n_lines: int = 3) -> None:
        self._answers = answers or make_review_answers(n_lines)

    def system_one(self, *, state: Any, questions: dict, **kwargs: Any) -> FakeResponse:
        # Return a score or noul for every question asked, falling back to defaults.
        resolved: dict[str, Any] = {}
        for key in questions:
            if key in self._answers:
                resolved[key] = self._answers[key]
            elif key.startswith("line_"):
                resolved[key] = FakeNoul(0.1)
            elif key.startswith("claim_"):
                resolved[key] = FakeNoul(0.1)
            elif key.startswith("src_"):
                resolved[key] = FakeChoice(choice="none")
            elif key.startswith("cov_"):
                resolved[key] = FakeChoice(choice="none")
            elif key == "biggest_gap":
                resolved[key] = FakeChoice()
            else:
                resolved[key] = FakeScore()
        return FakeResponse(resolved)


class FakeOpenAIClient:
    """An OpenAI client stub that returns a fixed completion text."""

    def __init__(self, text: str = "Jane Smith\nSoftware Engineer\n\nBuilt things.") -> None:
        self._text = text

    def __enter__(self) -> FakeOpenAIClient:
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    @property
    def chat(self) -> FakeOpenAIClient:
        return self

    @property
    def completions(self) -> FakeOpenAIClient:
        return self

    def create(self, **kwargs: Any) -> Any:
        class FakeUsage:
            prompt_tokens = 200
            completion_tokens = 100
            total_tokens = 300

        class FakeMessage:
            content = self._text

        class FakeChoice:
            message = FakeMessage()

        class FakeCompletion:
            model = "fake-model"
            choices = [FakeChoice()]
            usage = FakeUsage()

        return FakeCompletion()
