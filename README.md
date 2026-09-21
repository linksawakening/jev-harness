# Jev Task Harness

A specification for a self-hosted system that takes a project description, proposes an
agent team, and then runs a kanban board to completion with minimal human input. Semantic
judgments — task triage, agent selection, model routing, status classification, acceptance
verification — are delegated to [TypeSafe Jev](https://docs.typesafe.ai), a decision model
that returns typed, calibrated answers instead of generated text.

**Status:** specification, pre-implementation. The Jev numbers in the spec were measured
live against `jev-1.13.0`; the probe scripts that produced them are in [`probes/`](probes/).

## The idea

Code owns the loop. Jev owns the judgments. The LLM owns the content.

| Bucket | Owns | Never owns |
|---|---|---|
| Deterministic code | State machine, task DAG, scheduling, concurrency, budgets, checkpoints, arithmetic, persistence | Semantic interpretation |
| **Jev** (Choice / Noul / Score) | Bounded semantic judgments at named seams | Execution, authorization, state, arithmetic |
| Frontier LLM | Decomposition, agent prompts, code, prose, multi-hop reasoning | Gates, approvals, state transitions |

The user describes a project, the system proposes a decomposition and a team drawn from a
configured model roster, the user approves the starting configuration, presses **Go**, and
walks away. Open questions are resolved by deciding and logging an assumption rather than
stopping the run.

## Scope

The scope is deliberately narrow. Read this before the spec.

- **Self-contained.** One Python process, one SQLite file, one directory on disk. Nothing
  else needs to be installed or running for the system to work.
- **The interface is a locally hosted HTML dashboard.** The UI is a static HTML/CSS/JS
  dashboard served by the local process, talking to the local API. No build step, no
  package manager, no SPA framework, no CDN, no external service. Open the page, use the
  board.
- **No other harness.** This is not built on, wrapped around, or dependent on Hermes,
  Hermes Kanban, OpenCoder, or any other agent framework. It does not delegate its own loop
  to another agent. Any external agent process it uses is a subprocess the harness spawns
  and supervises itself; the loop stays here.
- **No GitHub Projects, and no external task board of any kind.** The board lives in local
  SQLite and is rendered by the dashboard. An external board would require an identity for
  every agent, a network round trip per transition, its own auth surface, and — with no
  transaction semantics — a reconciliation job instead of a correctness guarantee. None of
  that is needed here.
- **Single user, single machine.** Bound to localhost and the Tailscale interface. No auth
  beyond network locality, no multi-tenancy, no cloud.

## What's here

- [`SPEC.md`](SPEC.md) — the full specification
- `probes/` — the live measurement scripts behind the spec's numbers

### SPEC.md contents

- **§1–4** — purpose and scope, design principle, architecture, data model
- **§5** — the Jev decision seams, grouped by lifecycle stage, with primitive and shortlist rule per seam
- **§6** — versioned rubric files and their measured properties
- **§7** — the autonomy policy: escalation ladder, assumption ledger, authority ceiling
- **§8–12** — guardrails, dashboard, run lifecycle, failure recovery, observability
- **§13–14** — acceptance criteria for the harness, and operating modes
- **§15–17** — phased delivery, resolved decisions, deferred work

## Measured findings that shaped the design

These are why two design choices look the way they do. Probe scripts are in `probes/`.

**Jev's Score primitive is usable for a quantitative report, but the ladder wording moves
the answer.** Four ground-truth scenarios (clear miss / borderline pass / clean pass /
exceed) × three ladder shapes × four repeats: all three shapes ordered the scenarios
correctly, run-to-run sd `0.00–0.10` on a normalised 0–10 scale. But the *same state* scored
**6.69/10** under a magnitude ladder and **3.73/10** under an action ladder — straddling
the threshold on one and clearing it on the other. Consequence: gate on a categorical
3-rung action band, report the 10-rung artifact scale, and never compare scores across
rubric versions. Probe: `probes/jev_score_truth.py`.

**Score caps at 10 levels.** An 11-rung "0 to 10" ladder returns
`HTTP 400: Too many score levels. Must have at most 10 levels.` A literal 0–10 is not
expressible; the report ladder has 10 rungs and normalises to 0–10 for display.
Probe: `probes/jev_ladder_cap.py`.

## Running the probes

The probes need `TYPESAFE_API_KEY` in the environment or in `~/.hermes/.env`. They make
real billed requests — fractions of a cent each, but not free.

```bash
python3 probes/jev_score_truth.py    # truth tracking across 3 ladder shapes
python3 probes/jev_ladder_cap.py     # find the Score level cap
python3 probes/jev_score_probe.py    # single-state spread across repeats
```

## License

MIT
