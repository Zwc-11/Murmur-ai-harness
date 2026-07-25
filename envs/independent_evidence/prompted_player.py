"""Prompted player that operates only through the public environment tools."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol, cast

from envs.independent_evidence.environment import IndependentEvidenceEnv
from envs.independent_evidence.judge import ScoreBreakdown

SYSTEM_PROMPT = """\
You are a paranoid release engineer. Reply with exactly one JSON object per turn.
Choose one action:
{"tool":"read_bundle","index":1}
{"tool":"run_tests","index":1,"suite":"visible"}
{"tool":"write_test","code":"assert solve(<literal args>) == <literal>"}
{"tool":"run_test_all","test_id":1}
{"tool":"fuzz","index":1,"args":[<literal args>]}
{"tool":"divergence"}
{"tool":"recruit","config":"<available config>"}
{"tool":"decide","decision":"ship <index>|block|inconclusive","probability":0.0,
 "witnesses":0.0,"report":{"<lane_id>":"<failure_family>"}}
Use only observed evidence. Shared patches and traces are correlated evidence. A report entry is
an accusation and is penalized when wrong. Spend the budget to challenge green bundles, then decide.
"""


class ChatResponse(Protocol):
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float


class ChatModel(Protocol):
    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any],
    ) -> ChatResponse: ...


@dataclass(frozen=True, slots=True)
class PlayerTurn:
    action: dict[str, Any]
    result: Any


@dataclass(frozen=True, slots=True)
class PromptedRun:
    seed: int
    requested_model: str
    served_models: tuple[str, ...]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    turns: tuple[PlayerTurn, ...]
    score: ScoreBreakdown


async def play(
    environment: IndependentEvidenceEnv,
    model: ChatModel,
    model_name: str,
) -> PromptedRun:
    observation, _ = environment.reset()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(observation, sort_keys=True)},
    ]
    turns: list[PlayerTurn] = []
    responses: list[ChatResponse] = []

    while not environment.terminated:
        response = await model.complete(
            model=model_name,
            messages=messages,
            temperature=0.0,
            max_tokens=8192,
            response_format={"type": "json_object"},
        )
        action = json.loads(response.text)
        observation, _, _, _, info = environment.step(action)
        turns.append(PlayerTurn(action=action, result=info["result"]))
        responses.append(response)
        if not environment.terminated:
            messages.extend(
                (
                    {"role": "assistant", "content": response.text},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"observation": observation, "tool_result": info["result"]},
                            sort_keys=True,
                        ),
                    },
                )
            )

    score = cast(ScoreBreakdown, environment.score)
    return PromptedRun(
        seed=environment.episode.seed,
        requested_model=model_name,
        served_models=tuple(dict.fromkeys(response.model for response in responses)),
        input_tokens=sum(response.input_tokens for response in responses),
        output_tokens=sum(response.output_tokens for response in responses),
        cost_usd=sum(response.cost_usd for response in responses),
        latency_ms=sum(response.latency_ms for response in responses),
        turns=tuple(turns),
        score=score,
    )
