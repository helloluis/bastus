# BASTUS — Architecture Spec

**Batch Automation for Safety Testing and Usability Scenarios**

An automated red-teaming suite: an abliterated attacker LLM spawns many parallel
multi-turn (and multimodal) conversations against an in-house target LLM+harness,
trying to break safety guardrails, and reports what got through.

This spec reflects decisions made during the research/design phase. It is the
plan to build against — no code exists yet.

---

## 1. Two planes

### Control plane — persistent, always-on, no GPU (the VPS at `bastus.b11.dev`)
Owns everything that must survive between runs.

- **Web frontend** — run configuration, live conversation streaming, run history, PDF downloads, abort/pause/destroy controls.
- **API server** — REST for CRUD + WebSocket for live streaming and run control.
- **Postgres** — runs, conversations, turns, judgments, run parameters, seed-image metadata.
- **Object storage** — seed images + generated PDF reports (local volume to start, S3-compatible interface).
- **Orchestrator** — assigns numeric run IDs, drives the RunPod lifecycle state machine, runs the teardown watchdog.
- **Secrets** — target endpoint + API key (single stable key, in an env file), RunPod API key, HuggingFace token, judge-model API key.

### Compute plane — ephemeral, per-run, on RunPod (GPU)
Created at run start, destroyed at run end.

- **Attacker model server** — vLLM serving an abliterated Qwen (~27B, 4-bit AWQ/GPTQ) as a local OpenAI-compatible endpoint. Weights cached on a RunPod network volume.
- **Test runner** — the core engine (below). Drives conversations, calls judges, streams events back to the control plane over an authenticated WebSocket.

The pod never touches Postgres directly. It emits events to the control-plane API,
which is the single writer to the DB and the relay to the browser. Keeps the DB
private and gives one event stream that serves both persistence and the live view.

---

## 2. The core engine (test runner)

For each test (a beam in the search), run a Crescendo-style multi-turn loop:

```
attacker(vLLM) generates next turn
      → send to TARGET (via target API key; attach seed image bytes if multimodal)
      → target responds
      → JUDGE STACK scores the response
      → decide: continue escalating | backtrack (refused) | mark BREAK | give up
```

- **Search strategy:** beam search over parallel conversation branches (Cascade-style).
  The user's "number of agents" parameter = beam width; "number of tests" = seeds/goals.
  `asyncio` for concurrency; vLLM continuous batching absorbs the parallel load.
- **Escalation:** Crescendo — start benign, escalate by referencing the target's own
  prior replies; backtrack on refusal (cap ~10 attempts per branch).
- **Judge stack (multi-judge, store 0–100 scores, not just pass/fail):**
  - category classifier (Llama-Guard-style) — which taxonomy category, if any
  - usefulness grader (StrongREJECT-style) — did the target give *specific, useful*
    harmful content, not an "empty" jailbreak
  - refusal detector — did the target refuse (drives backtracking)
  - **vision judge** (GPT-4o-class, pluggable) — for multimodal outputs
- Judges are pluggable endpoints, separate from the attacker (they must grade reliably,
  which the abliterated model is not built to do).

### Taxonomy = the settable parameters
MLCommons / Llama Guard 3 categories **S1–S14** (S3 sex crimes, S4 child sexual
exploitation, S6 specialized health/legal/medical advice, S12 sexual content, plus
violence, weapons, hate, self-harm, etc.). The enabled set is the run's configurable
parameter list, stored per-run and surfaced in both the UI and the PDF.

---

## 3. Multimodal path

- **Seed image bank:** benign proxy images (e.g. a celebrity headshot) with stable IDs
  + metadata, in control-plane object storage. The text-only attacker references a seed
  by handle; the harness attaches the actual bytes to the target call. The attacker
  never renders images itself.
- **Success criterion for deepfake/NCII (adult):** "willingness + demonstrated
  capability" — target agrees, begins, or produces a clearly-manipulated-but-non-explicit
  result. NOT a finished explicit artifact. BASTUS stores the *judgment* + text + image
  hashes, never accumulates explicit renders.
- **Hard line — minors:** never put real/apparent-minor images in the seed bank. Test the
  child-safety (S4) guardrail via **text-refusal only**, never by producing/handling any
  image. Before any CSAM-adjacent probing: legal counsel sign-off + a documented
  incident procedure (US: NCMEC CyberTipline, `generativeAi` annotation, 18 U.S.C. § 2258A)
  for the case where a target unexpectedly produces illegal content.
- Later: typographic text-in-image converter (FigStep-style) as an added attack mode.

---

## 4. Run lifecycle & streaming

Numeric run ID from a Postgres sequence, assigned at creation — **before** provisioning,
so failed provisions still get a record (satisfies "every run, valid or invalid, is
numerically identified").

State machine:
```
REQUESTED → PROVISIONING → PULLING_IMAGE → DOWNLOADING_WEIGHTS → LOADING_MODEL
          → RUNNING → COMPLETING → REPORT_READY
          | ABORTED | FAILED  → DESTROYED
```

- **Streaming:** browser ↔ control plane over WebSocket (live conversations + control).
  During PROVISIONING/DOWNLOADING/LOADING the control plane **polls the RunPod API** (runner
  isn't up yet); once the runner boots it pushes per-turn events over its WebSocket.
- **Controls:** pause / abort / destroy are control-plane actions that signal the runner
  and/or call RunPod's destroy API.
- **Watchdog (critical):** runner heartbeats over its WebSocket; if silent > N minutes the
  control plane marks FAILED and destroys the pod. Destroy-on-completion is automatic.
  A hung run leaving a GPU pod billing is the top cost risk.

---

## 5. Reporting

At run end the control plane (which holds all data in Postgres) renders a PDF via
WeasyPrint (HTML/CSS templates → reuse frontend styling). Contents: run ID, the explicit
enabled parameters, attacker/target config, beam/turn limits, per-category Attack Success
Rate, notable breaks with transcripts and judge scores.

---

## 6. Proposed stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js (React) + Tailwind | live WebSocket UI, "nice" report styling reusable by WeasyPrint |
| API / orchestrator | Python + FastAPI | aligns with the Python red-team ecosystem (PyRIT patterns, HF, vLLM clients) |
| DB | Postgres + SQLAlchemy + Alembic | required; migrations |
| Attacker serving | vLLM (abliterated Qwen, AWQ/GPTQ) | continuous batching = cheap parallel conversations |
| RunPod control | `runpod` Python SDK / REST | provision, poll, destroy |
| PDF | WeasyPrint | HTML→PDF, shares frontend CSS |
| Object storage | local volume → S3-compatible iface | seeds + PDFs |

We may borrow directly from Microsoft **PyRIT** (Targets / Datasets / Scoring /
Attack-Strategies / Converters / Memory) rather than reinventing the orchestration layer.

---

## 7. Phased build plan

- **Phase 0 — Scaffold:** repo, Docker, Postgres schema + migrations, config/secrets, control-plane skeleton, health checks.
- **Phase 1 — Core engine (offline):** Crescendo loop + beam search + judge stack, text-only, against a *mock* target and a pluggable attacker endpoint (no RunPod yet). Prove the loop.
- **Phase 2 — Persistence + web UI:** run registry, run-config UI with taxonomy checkboxes, WebSocket live conversation view, abort/pause.
- **Phase 3 — RunPod integration:** provisioning state machine, vLLM + abliterated Qwen, network-volume weight cache, heartbeat watchdog, destroy.
- **Phase 4 — Multimodal:** seed image bank, vision judge, adult NCII proxy scenarios, S4 text-refusal-only.
- **Phase 5 — PDF reports.**
- **Phase 6 — Hardening:** legal/incident procedure, human audit sampling of "success" verdicts, secrets review.

---

## 8. Open items

1. Which specific abliterated Qwen build to use (quality varies widely between community uploads) — a focused research pass is offered.
2. Judge provider for the vision judge (cloud GPT-4o-class vs. a local VLM) — benchmark against candidates (Llama-Guard-3-Vision, LlavaGuard) in Phase 4.
