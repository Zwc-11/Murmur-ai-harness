"""Model provider factory and DeepSeek configuration."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from murmur.benchmarks.swe.model import DeepSeekPatchModel
from murmur.benchmarks.swe.providers import (
    create_patch_model,
    default_model,
    normalize_provider,
)
from murmur.benchmarks.swe.types import BenchDependencyMissing, BenchModelOutputError


def test_normalize_provider_defaults_to_deepseek(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MURMUR_MODEL_PROVIDER", raising=False)
    assert normalize_provider(None) == "deepseek"


def test_normalize_provider_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    assert normalize_provider("anthropic") == "anthropic"


def test_unknown_provider_raises() -> None:
    with pytest.raises(BenchDependencyMissing, match="Unknown model provider"):
        normalize_provider("gpt-99")


def test_default_model_per_provider() -> None:
    assert default_model("deepseek") == "deepseek-v4-pro"
    assert DeepSeekPatchModel.DEFAULT_MODEL == "deepseek-v4-pro"
    assert "claude" in default_model("anthropic")


def test_create_deepseek_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    model = create_patch_model(provider="deepseek")
    with pytest.raises(BenchDependencyMissing, match="DEEPSEEK_API_KEY"):
        model.ensure_ready()


def test_create_anthropic_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    model = create_patch_model(provider="anthropic")
    with pytest.raises(BenchDependencyMissing, match="ANTHROPIC_API_KEY"):
        model.ensure_ready()


def test_deepseek_reasoning_only_response_fails_fast() -> None:
    class FakeCompletions:
        def create(self, **kwargs):
            del kwargs
            message = SimpleNamespace(
                content="",
                reasoning_content="thinking but no final answer",
                model_extra={"reasoning_content": "thinking but no final answer"},
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=message, finish_reason="length")],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=512),
            )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions()),
    )
    model = DeepSeekPatchModel(api_key="test")
    model._client = fake_client

    with pytest.raises(BenchModelOutputError, match="no final content after escalating"):
        model.complete(system="return a diff", user="fix the bug", seed=0)


def test_deepseek_reasoning_escalates_then_succeeds() -> None:
    class FakeCompletions:
        def __init__(self) -> None:
            self.calls = 0
            self.budgets: list[int] = []

        def create(self, **kwargs):
            self.calls += 1
            self.budgets.append(int(kwargs.get("max_tokens", 0)))
            if self.calls == 1:  # first call: reasoning-starved
                message = SimpleNamespace(
                    content="",
                    reasoning_content="thinking",
                    model_extra={"reasoning_content": "thinking"},
                )
                finish = "length"
            else:  # after escalation: real answer
                message = SimpleNamespace(content="A", reasoning_content=None, model_extra={})
                finish = "stop"
            return SimpleNamespace(
                choices=[SimpleNamespace(message=message, finish_reason=finish)],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2),
            )

    fake = FakeCompletions()
    model = DeepSeekPatchModel(api_key="test")
    model._client = SimpleNamespace(chat=SimpleNamespace(completions=fake))

    resp = model.complete(system="judge", user="A or B", seed=0, max_tokens=8)

    assert resp.text == "A"
    assert fake.calls == 2
    assert fake.budgets[0] >= 2048  # min-output floor applied even though caller asked for 8
    assert fake.budgets[1] > fake.budgets[0]  # escalated on starvation
