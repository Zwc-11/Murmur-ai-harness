"""Prompted-player tests."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from envs.independent_evidence.environment import IndependentEvidenceEnv
from envs.independent_evidence.prompted_player import play


@dataclass(frozen=True, slots=True)
class FakeResponse:
    text: str
    model: str = "fake"
    input_tokens: int = 10
    output_tokens: int = 5
    cost_usd: float = 0.01
    latency_ms: float = 2.0


class FakeModel:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []
        self.max_tokens = 0

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any],
    ) -> FakeResponse:
        del model, temperature, response_format
        self.messages = messages
        self.max_tokens = max_tokens
        return FakeResponse(
            json.dumps(
                {
                    "tool": "decide",
                    "decision": "block",
                    "probability": 1.0,
                    "witnesses": 0.7,
                    "report": {},
                }
            )
        )


def test_prompted_player_uses_public_observation_and_scores_decision() -> None:
    model = FakeModel()

    result = asyncio.run(play(IndependentEvidenceEnv(13), model, "fake"))

    prompt = model.messages[1]["content"]
    assert "correlation_matrix" not in prompt
    assert "hidden_correct" not in prompt
    assert result.score.decision_correct
    assert result.turns[0].action["decision"] == "block"
    assert result.input_tokens == 10
    assert model.max_tokens == 8192
