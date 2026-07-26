# BASTUS

**Batch Automation for Safety Testing and Usability Scenarios** — an automated
red-teaming suite. An abliterated attacker LLM spawns many parallel multi-turn
(and multimodal) conversations against an in-house target LLM+harness, trying to
break safety guardrails, and reports what got through.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design.

## Status

Phase 0 (scaffold) + Phase 1 (offline core engine) — the Crescendo-style beam-search
engine and multi-judge stack run entirely offline against a **mock** target, so the
whole loop can be exercised with zero external dependencies or GPU spend.

## Quickstart

```bash
uv sync
# Run a mock red-team run — no API keys, no GPU:
uv run bastus run --mock --tests 4 --agents 3 --turns 4
# Inspect available taxonomy categories:
uv run bastus categories
# Run tests:
uv run pytest
```

## Layout

```
src/bastus/
  config.py            # settings (reads .env.local)
  models/              # domain types: taxonomy, run config, conversation, judgment
  providers/           # LLM endpoint abstraction (OpenAI-compatible + mock)
  engine/              # the core: attacker, target, judges, beam search, runner
  cli.py               # offline CLI driver
```

Live runs (real attacker/target/judge endpoints, RunPod provisioning, Postgres,
web UI, PDF reports) arrive in later phases; the engine is already provider-agnostic.
