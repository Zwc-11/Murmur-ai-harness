# Run Murmur On Your Agent In 10 Minutes

Murmur wraps an agent. It does not replace your runtime. The harness runs the
same task many times, records neutral events, judges outcomes independently, and
reports reliability as a distribution.

## 1. Install

```bash
python -m pip install -e ".[dev]"
murmur init
pytest -q
ruff check murmur tests
```

## 2. Run The Free Demo

```bash
murmur agents list
murmur run --n 30 --seed 7
murmur trace --n 12 --seed 7 --replay
murmur gate --suite synthetic --n 20 --k 5
```

Open `.murmur/fan.html` or `.murmur/trace.html` after the run. These reports are
derived from the event log, not from model self-report.

## 3. Wrap A Real Agent

Implement `AgentPort`:

```python
class MyAgent:
    async def run(self, task, gateway):
        await gateway.step(index=0, phase="plan")
        await gateway.model(
            model="my-model",
            input_tokens=100,
            output_tokens=50,
            finish_reason="stop",
        )
        result = await gateway.call("my_tool", {"input": task.prompt})
        return str(result)
```

For observational frameworks, import traces instead of executing through Murmur:

```python
from murmur.adapters.trace import OpenAIAgentsTraceImporter

events = OpenAIAgentsTraceImporter().import_events(
    records,
    run_id="run_external",
    task_id="my.task",
)
```

Supported public adapter surfaces:

- OpenAI Agents SDK trace import.
- Claude Code hook/transcript import.
- Google ADK trace import.
- LangGraph `astream_events` live adapter and trace import.

## 4. Run A Real-Model Benchmark

Use real benchmarks only for real measured claims. For the hard landing-site
task with DeepSeek, follow the step-by-step
[runbook](benchmarks/RUNBOOK.md) (`murmur doctor --ping`, then
`murmur agents run deepseek-website --n 10 --task hard`).

For SWE-bench Verified, the gate runs a real agent + the official Docker
evaluator:

```bash
python -m pip install -e ".[bench]"
export DEEPSEEK_API_KEY=...   # or ANTHROPIC_API_KEY + MURMUR_MODEL_PROVIDER=anthropic
murmur gate --suite swe-bench-verified --real-agent --n 10 --k 5
```

If Docker, the dataset, or a real model key is missing, Murmur exits instead of
printing a fake benchmark number.

