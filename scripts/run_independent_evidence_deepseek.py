"""Run one DeepSeek reference player and write its mechanical score."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from envs.independent_evidence.environment import IndependentEvidenceEnv
from envs.independent_evidence.prompted_player import play
from murmur.adapters.models.openai_compatible import OpenAICompatibleModel
from murmur.config import load_project_env
from murmur.core.model_port import ModelPrice

MODEL = "deepseek-v4-pro"
SEED = 82


async def run() -> None:
    load_project_env(start=Path.cwd())
    model = OpenAICompatibleModel(
        base_url="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
        prices={MODEL: ModelPrice(input=0.80, output=3.20)},
    )
    result = await play(IndependentEvidenceEnv(SEED), model, MODEL)
    path = (
        Path(__file__).parents[1]
        / "envs"
        / "independent_evidence"
        / "audit"
        / "deepseek-reference.json"
    )
    path.write_text(
        json.dumps(asdict(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"{result.requested_model}: decision={result.score.decision}, "
        f"correct={result.score.decision_correct}, score={result.score.total:.3f}, "
        f"turns={len(result.turns)}, cost_usd={result.cost_usd:.6f}"
    )


if __name__ == "__main__":
    asyncio.run(run())
