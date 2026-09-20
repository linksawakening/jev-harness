# Jev Task Harness

A specification for a self-hosted system that takes a project description, proposes an
agent team, and runs a kanban board to completion with minimal human input. Semantic
judgments — task triage, agent selection, model routing, status classification, acceptance
verification — are delegated to [TypeSafe Jev](https://docs.typesafe.ai), a decision model
that returns typed, calibrated answers instead of generated text.

**Status:** specification, pre-implementation. The numeric claims in the spec were measured
live against `jev-1.13.0` and the GitHub GraphQL API; the probe scripts that produced them
are in [`probes/`](probes/).

## The idea

Code owns the loop. Jev owns the judgments. The LLM owns the content.

| Bucket | Owns | Never owns |
|---|---|---|
| Deterministic code | State machine, task DAG, scheduling, concurrency, budgets, checkpoints, arithmetic, permissions, persistence | Semantic interpretation |
| **Jev** (Choice / Noul / Score) | Bounded semantic judgments at named seams | Execution, authorization, state, arithmetic |
| Frontier LLM | Decomposition, agent prompts, code, prose, multi-hop reasoning | Gates, approvals, state transitions |

The user describes a project, the system proposes a decomposition and a team drawn from a
live model roster, the user approves the starting configuration, presses **Go**, and walks
away. Open questions are resolved by deciding and logging an assumption rather than
stopping the run.

## What's here

- [`SPEC.md`](SPEC.md) — the full specification
- `probes/` — the live measurement scripts behind the spec's numbers

### SPEC.md contents

- **§1–4** — purpose, design principle, architecture, data model
- **§5** — the Jev decision seams, grouped by lifecycle stage, with primitive and shortlist rule per seam
- **§6** — versioned rubric files and their measured properties
- **§7** — the autonomy policy: escalation ladder, assumption ledger, authority ceiling
- **§8–12** — guardrails, UI, run lifecycle, failure recovery, observability
- **§13** — acceptance criteria for the harness, and operating modes
- **§14–16** — phased delivery, resolved decisions, deferred work
- **§17** — annex: GitHub Projects as an optional interface (mirror not source, measured API cost, issue triage in maintenance mode)

## Measured findings that shaped the design

These are why several design choices look the way they do.

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

**GitHub Projects writes are cheap; reads are not.** Measured 2026-09-20: a field write is
**1 GraphQL point**, an issue create is 1 point, but a board read is N+1 — 5 items cost 6
points and 20 items cost **102 points**. Polling a 100-item board every 10 seconds exhausts
the 5,000 points/hour budget in under four minutes. Consequence: GitHub sync is
event-driven with an outbox, never polling, and reads happen only on explicit user action
or a post-run reconcile. Probe: `probes/gh_cost_clean.sh`.

## Running the probes

The Jev probes need `TYPESAFE_API_KEY` in the environment or in `~/.hermes/.env`. They
make real billed requests — fractions of a cent each, but not free.

```bash
python3 probes/jev_score_truth.py    # truth tracking across 3 ladder shapes
python3 probes/jev_ladder_cap.py     # find the Score level cap
python3 probes/jev_score_probe.py    # single-state spread across repeats
bash    probes/gh_cost_clean.sh      # GraphQL points per Projects v2 operation
```

`gh_cost_clean.sh` creates and deletes a throwaway GitHub project. It requires a token with
the `project` scope.

## License

MIT
