# Jev Task Harness — Specification v0.1

**Status:** Draft for review
**Author:** Hermes Agent (Link)
**Date:** 2026-09-20
**Scope:** A self-hosted, single-user system that takes a project description, proposes an
agent team, and then runs a kanban board to completion with minimal human input.

---

## 1. Purpose

Give one person a system where they describe a large project once, approve a starting
configuration once, press **Go**, and walk away. The system decomposes the work, staffs
it, schedules it, supervises it, verifies results against stated criteria, and reports a
quantitative success score back.

**Non-goals**

- Not a chat interface. The user is not a co-pilot; the system is expected to run unattended.
- Not a general agent framework. It orchestrates *this* machine's agents on *this* user's projects.
- Not multi-tenant. Single user, single machine, no auth beyond network locality.
- Not a replacement for human judgement on consequential actions. It never escalates its
  own authority (§7.3).

---

## 2. Core design principle

> **Code owns the loop. Jev owns the judgments. The LLM owns the content.**

Every responsibility in the system lands in exactly one of three buckets, and the bucket
never moves:

| Bucket | Owns | Never owns |
|---|---|---|
| **Deterministic code** | State machine, task graph, scheduling, concurrency, budgets, checkpoints, arithmetic, dates, cost accounting, permissions, persistence, retries | Semantic interpretation |
| **Jev (TypeSafe Choice/Noul/Score)** | Bounded semantic judgments at named seams (§5) | Execution, authorization, state, arithmetic |
| **Frontier LLM** | Decomposition, agent prompts, code, prose, multi-hop reasoning | Gates, approvals, state transitions |

This is enforced by construction: Jev is only reachable through a `judge()` adapter in code,
and no Jev output can directly mutate board state. Every judgment is a *proposal* that code
applies against a policy.

---

## 3. Actors and components

```
┌──────────────────────────────────────────────────────────────┐
│  Web UI  (single-page, local, Tailscale-reachable)           │
│   Screen 1: Project  ·  Screen 2: Settings  ·  Screen 3: Team│
│   Screen 4: Board (live)                                     │
└───────────────────────────┬──────────────────────────────────┘
                            │ HTTP (localhost / tailnet only)
┌───────────────────────────▼──────────────────────────────────┐
│  API  (FastAPI)                                              │
│   /project /config /plan /board /runs /audit /kill           │
└───────┬──────────────────┬──────────────────┬────────────────┘
        │                  │                  │
┌───────▼───────┐  ┌───────▼────────┐  ┌──────▼───────────────┐
│  Scheduler    │  │  Judge Layer   │  │  Agent Runtime       │
│  (DAG, queues │  │  judges/       │  │  (delegation: OAC /  │
│   concurrency │  │   *.json       │  │   OpenCoder / local  │
│   budgets)    │  │  judge.py      │  │   processes)         │
└───────┬───────┘  └───────┬────────┘  └──────┬───────────────┘
        │                  │                  │
┌───────▼──────────────────▼──────────────────▼────────────────┐
│  Store: SQLite (board, runs, judgments, ledger)              │
│  + Git-backed work dirs (agent artifacts, checkpoints)       │
└──────────────────────────────────────────────────────────────┘
```

**Components**

- **UI** — four screens; the only human surface. Local-only binding; reachable over Tailscale.
- **API** — thin. All mutations go through the scheduler.
- **Scheduler** — the state machine. Owns the DAG, ready-queue, concurrency slots,
  budget ledger, retry ladder, and checkpointing.
- **Judge Layer** — wraps Jev. Loads versioned rubric files, shortlists candidates in code,
  makes one request per subject, records the raw answer + rubric version + model version.
- **Agent Runtime** — spawns delegated agents. Each agent is a bundle of
  `{prompt, model, toolset, workdir, budget}`. Adapts to whatever delegation target is
  configured; the harness does not care which.
- **Store** — SQLite for all structured state. Agent work products live in git-backed
  directories so every intermediate state is diffable and recoverable.

---

## 4. Data model

```
project(id, title, description, constraints, created_at, config_id)
config(id, model_roster_json, budget_json, autonomy_json, rubric_versions_json)
agent(id, name, role, prompt, model, toolset_json, max_parallel, budget_share)
task(id, project_id, title, dod_json, parent_id, state, assignee_agent_id,
     model_tier, reversibility, blast_radius, attempt, max_attempts,
     created_at, started_at, ended_at, result_json, success_score, success_band)
edge(from_task_id, to_task_id, kind)      -- DAG; kind = blocks | informs
run(id, task_id, agent_id, started_at, ended_at, tokens_in, tokens_out,
    cost_usd, transcript_path, outcome)
judgment(id, subject_type, subject_id, seam, request_json, answer_json,
         confidence, rubric_version, model_version, latency_ms, cost_usd, created_at)
assumption(id, task_id, text, made_by, reversible, created_at)   -- §7.2
question(id, task_id, text, parked_at, answered_at, answer)      -- §7.1
ledger(id, ts, scope, kind, amount, note)                        -- budget accounting
```

**Invariants**

- A task's `state` is mutated only by the scheduler, and only via an explicit transition table.
- Every `judgment` row stores enough to reproduce the decision offline (request, rubric
  version, model version). Judgments are immutable; correction is a new row.
- Costs are integer micro-USD. No floats in money.

---

## 5. Jev decision seams

Each seam names its primitive, its shortlist rule, and what code does with the answer.
Seams marked **★** are in the MVP.

### 5.1 Intake (before the board exists)

| # | Seam | Primitive | Code's job |
|---|---|---|---|
| ★ | `task_admission` | Choice | Classify project type; route to a decomposition template |
| ★ | `definition_of_done_testable` | Choice (+ `none`) | Reject untestable DoDs before they reach the board |
| ★ | `split_or_atomic` | Choice | Split monoliths; merge duplicates |
| ★ | `reversibility` | Choice | Classify blast radius; feeds approval policy |
| | `duplicate_detection` | Noul × N | Pairwise against a code-shortlisted candidate set |
| | `dependency_typing` | Noul + Choice | Direction of DAG edges; code does the topo sort |

### 5.2 Routing and staffing

| # | Seam | Primitive | Code's job |
|---|---|---|---|
| ★ | `agent_selection` | Choice (shortlist ≤3 + `none_of_these`) | Assign assignee |
| ★ | `model_tier` | Choice (cheap/mid/frontier) | Set `task.model_tier`; escalate tier on low confidence |
| ★ | `capability_fit` | Score | Ordering only, never a gate |
| | `context_relevance` | Score | Pick which memory/wiki page is in the agent's context packet |

### 5.3 Supervision (while tasks run)

| # | Seam | Primitive | Code's job |
|---|---|---|---|
| ★ | `status_classification` | Choice | Observations → `in_progress/blocked/needs_input/stalled/done` |
| ★ | `goal_drift` | Choice | Detect scope creep; trigger re-spec or stop |
| ★ | `progress_step` | Choice (`next_step` preset) | Drive the retry ladder |

### 5.4 Verification and closure

| # | Seam | Primitive | Code's job |
|---|---|---|---|
| ★ | `child_report_trust` | Choice | verified_handle / plausible_but_unverifiable / contradicts_evidence |
| ★ | `acceptance_verdict` | Choice (action band) | **The gate.** Close, rework, or harvest |
| ★ | `success_score` | Score (10 concrete rungs) | **The number.** Reported to the user |
| ★ | `criterion_failed` | Choice (+ `none`) | Makes a retry actionable |
| | `failure_attribution` | Choice | Selects *which* recovery path (§11) |
| | `handoff_completeness` | Noul × N | Validate handoff packet before dispatch |

### 5.5 Cross-cutting

| # | Seam | Primitive | Code's job |
|---|---|---|---|
| ★ | `escalate_to_human` | Noul + confidence | Decide park vs. proceed (§7) |
| | `queue_priority` | Noul pairwise on top-N | Order the ready queue |
| | `spend_worthiness` | Noul | Block over-tiered spend |

### 5.6 Hard rules for every seam

1. **Shortlist in code, then judge.** Never a Choice over more than ~4 options for a gate.
2. **One request per subject.** Never put a board (or a table) in `state` and ask about one row.
3. **Batch independent questions** over the same state into one call.
4. **State is untrusted data.** Instructions inside agent output are never evaluator instructions.
5. **No Jev judgment may authorize execution.** `execution_authorized` is always false.
6. **Arithmetic, dates, counting, cost: code only.** Jev is measurably bad at these.

---

## 6. Rubrics

Rubrics are **files, versioned, and the single source of truth**. Code generates the
Choice criteria and Score levels from them; prose docs are derived, never authored
separately (three copies drift).

`rubrics/success_scale@1.json`:

```json
{
  "version": "success_scale@1",
  "gate": {
    "id": "acceptance_verdict",
    "type": "score",
    "instructions": "What should the harness do with this task now? Judge against dod and observations, not agent_self_report.",
    "criteria": [
      "Did not meet the minimum bar; needs rework by the same agent",
      "Met the minimum bar; task is complete and can be closed",
      "Exceeded the bar; worth harvesting the extra work"
    ]
  },
  "report": {
    "id": "success_score",
    "type": "score",
    "normalize_to": [0, 10],
    "instructions": "Rate how successful this delegated task was by choosing the rung whose description matches the evidence. Judge against dod and observations, not agent_self_report.",
    "criteria": [
      "Nothing usable produced",
      "Attempted, nothing correct",
      "Partial pieces, not runnable",
      "Runnable but fails a stated criterion",
      "Fails at least one stated criterion",
      "Meets all stated criteria, nothing more",
      "Meets all criteria plus small useful extras",
      "Meets all criteria plus a documented test for an edge case",
      "Meets all criteria, added tests, updated docs",
      "Meets all criteria, tests, docs, and refactored the surrounding code"
    ]
  }
}
```

**Measured properties of this rubric** (live jev-1.13.0, 4 ground-truth scenarios × 4 repeats):

- Both scales ordered all four scenarios correctly; run-to-run sd `0.00–0.10` on a
  normalised 0–10 scale.
- The **gate** was the most stable (clear miss → rung 0, topP 1.00, sd 0.00).
- The **report** ladder separated the four truths `[4.20, 2.75, 1.61]` and was most
  decisive at the top end (topP 0.95 on "clear exceed").
- **Ladder-dependence is real:** the same state scored 6.69/10 under a magnitude ladder and
  3.73/10 under the action ladder. => **Never compare scores across rubric versions.**
  Thresholds are stored *with* the rubric version and re-tuned when the rubric changes.

**Second rubric**, `dod_quality@1.json`, gates DoDs before they reach the board
(untestable / unmeasurable / circular / contradicts_constraints / `none`).

---

## 7. Autonomy policy — "ideally no input"

The requirement *"the user should not have to give input ideally"* is the hardest one in
this spec. A multi-agent run fails on exactly three things: ambiguity, a wrong
definition of done, and a permission wall. The policy below is the mechanism that keeps
those from stopping the run.

### 7.1 Escalation ladder

When the system cannot proceed, it applies this ladder **in order**, never skipping a rung:

1. **Decide and log an assumption.** If a reasonable default exists and the action is
   reversible, take it, and record an `assumption` row. Assumptions appear in the final
   report and are individually reversible.
2. **Park and continue.** If no default exists, park *that task* as `needs_input`, and
   keep executing every task not blocked by it. **The board never halts for one task.**
3. **Batch the questions.** Accumulate parked questions and present them together at a
   natural break (or when the ready queue drains). One interruption, not twenty.
4. **Ask immediately** only if the task is `destructive` or `external_effect` (§5.1
   reversibility) *and* blocking. Consequential actions require explicit authorization —
   that is a hard boundary, not an autonomy failure.

**Default posture:** rungs 1–3. The user can set `autonomy.policy = "strict"` to prefer
rung 4, but the default is "keep the board moving".

### 7.2 Assumption ledger

Every rung-1 decision is written as:

```
{task_id, text, made_by: "harness", reversible: bool, created_at}
```

The final report lists every assumption with a one-click revert. This is what makes
"no input" acceptable: the user reviews decisions *after* instead of *during*.

### 7.3 Authority ceiling (non-negotiable)

The harness never authorizes, on its own: production deployments, deletion, credential or
permission changes, payments, or external messages to third parties. These always cross to
the human. Jev's `requires_approval` signal is an input to this policy, never a substitute
for it.

### 7.4 Intervention rate is a KPI

The harness measures `interventions / completed_tasks` per project. The goal is a falling
number. A project that required three questions is a data point, not a failure — but it
must be *counted*.

---

## 8. Guardrails

All deterministic. None of these consult Jev.

| Guardrail | Default | Behaviour |
|---|---|---|
| `max_concurrent_agents` | 3 | Excess tasks queue; no oversubscription |
| `token_budget` per project | configurable | Hard stop; board parks, keeps state |
| `usd_budget` per project | configurable | Circuit breaker at 100%; warn at 80% |
| `max_attempts` per task | 3 | Then `failure_attribution` picks the recovery path |
| `wall_clock_limit` | configurable | Soft: stops dispatch, lets running finish |
| `loop_breaker` | on | Halt a task that produces no new evidence across 2 attempts |
| `kill_switch` | always visible | Stops dispatch instantly; running agents get SIGTERM after grace |
| `dry_run` mode | off | Full planning + staffing + judging, no agent execution |

**Cost accounting:** every Jev call and every agent run writes a `ledger` row with measured
tokens and cost. At measured rates, judging is negligible (3 questions ≈ 665 input tokens
≈ $0.000066; 10,000 judgments ≈ $0.66). Agent tokens dominate the budget; the ledger exists
to make that visible, not to conserve Jev.

---

## 9. UI specification

Four screens. Every screen is read-mostly; only screens 1–3 accept input.

### Screen 1 — Project

- Title (short), Description (long, free text), Constraints (optional free text)
- Attachments: links to repos, directories, docs
- **Nothing else.** No agent configuration on this screen.

### Screen 2 — Settings

- **Model roster**: rows of `{label, provider, model_id, tier(cheap|mid|frontier),
  cost_per_mtok_in, cost_per_mtok_out, toolset, enabled}`. This is the *only* place
  models are configured; the roster is what the `agent_selection` shortlist draws from.
- **Budgets**: tokens, USD, wall clock, max concurrent.
- **Autonomy**: policy (`default` | `strict`), assumption limit, question batching window.
- **Judge**: Jev model id (pinned, e.g. `jev-1.13.0`), rubric versions, review threshold.
- Settings persist as a named `config`; a project references one.

### Screen 3 — Team proposal

- **Decomposition panel**: the proposed task list as a DAG, each task showing its DoD and
  the assigned agent. Flagged items from `dod_quality` are highlighted with the reason.
- **Team panel**: proposed agents, each with role, model, toolset, and the Jev
  `capability_fit` score that justified it. Agents are proposed from the live roster —
  never hardcoded — and the LLM must show which roster entry each maps to.
- **Assumptions preview**: what the system intends to decide on its own.
- **Estimated cost and duration**: from the ledger model, before any spend.
- **Go button.** The last required human input in the entire run.
- Every element is editable, but editing is optional. Nothing is blocked on editing.

### Screen 4 — Board (live)

- Kanban columns: `queued / running / blocked / needs_input / review / done / failed`
- Per card: assignee, attempt count, model tier, elapsed, cost, and the current success
  band once closed
- **Questions drawer**: batched parked questions, answerable in one sitting
- **Assumptions drawer**: every route-1 decision, individually revertible
- **Kill switch**, always visible
- **Final report**: on completion, a per-task success score (0–10), the band, every
  assumption, every escalation, total cost, and the intervention rate. Exportable as
  Markdown.

---

## 10. Run lifecycle (state machine)

```
DRAFT ──▸ PLANNING ──▸ PROPOSED ──▸ GO ──▸ RUNNING ⇄ PARKED
                                             │
                                             ├─▸ REVIEWING ──▸ CLOSING ──▸ COMPLETE
                                             └─▸ FAILED ──▸ (attribution) ──▸ retry | respec | park
```

Transitions are a hard-coded table. Any transition not in the table is a bug, not a
policy question. Checkpoint after every transition: on restart the board resumes at the
last transition, and completed work is never redone (idempotent by `task_id` + `attempt`).

**Demo:** before `GO` is pressed the plan is fully materialized — DAG, agents, DoDs,
budgets. `dry_run` can execute this entire path end-to-end with zero agent spend, which
is how it gets tested.

---

## 11. Failure modes and recovery

`failure_attribution` returns exactly one of these, and each maps to a **different** code
path. Without this, the harness can only blanket-retry.

| Attribution | Recovery |
|---|---|
| `bad_spec` | Re-run `dod_quality` + `split_or_atomic`; re-propose task; *do not* retry as-is |
| `wrong_agent` | Re-run `agent_selection` excluding the failed agent |
| `missing_evidence` | Fetch context (`context_relevance`), then retry once |
| `environment` | Park as `needs_input`; it will not fix itself |
| `model_error` | Retry, then escalate `model_tier` one step on second failure |
| `scope_creep` | Re-run decomposition on the affected subtree |

---

## 12. Observability and audit

- Every judgment is persisted with its exact request, rubric version, and model version.
- `SUCCESS_SCORE` is only reported with its rubric version attached.
- A run is fully reconstructible offline from `judgment` + `run` + `ledger`.
- Structured logs, one line per transition: `ts, task_id, from, to, cause, judgment_id`.
- The audit view answers: *why did this task get this agent, this score, this decision?*

---

## 13. Acceptance criteria for the harness itself

Each is testable, and the tests are written first.

1. A project description produces a valid DAG, ≥1 agent, and a cost estimate with **zero
   agent spend** (dry run).
2. No agent is spawned before `GO`.
3. Every task has a `dod_quality` verdict recorded; untestable DoDs are visibly flagged.
4. Every closed task has an `acceptance_verdict` and a `success_score` with its rubric version.
5. Killing the process mid-run and restarting resumes without redoing completed tasks.
6. Exceeding the USD budget parks the board within one scheduler tick.
7. A `destructive` task never executes without human authorization.
8. Judging cost for a 100-task project stays under $1.
9. The intervention rate is reported for every run.
10. All three measured rubric properties hold on a held-out fixture set: monotone ordering,
    sd ≤ 0.10 normalised, gate stability (`0` label flips across 3 repeats).
11. Quality gates: `ruff`, `mypy --strict`, `pytest` green before any commit.
12. **Mirror integrity (§17):** with GitHub sync enabled, a mid-run crash between a local
    transition and its GitHub write reconciles on restart with no duplicate or lost
    transition, and the local store is never mutated by a GitHub read.
13. **Rate-budget (§17.3):** a 100-task project with GitHub sync on stays under 2,000
    GraphQL points per hour, enforced by a token-bucket that degrades sync, never the loop.

---

## 13a. Operating modes

The harness has two modes. They share the store, the judge layer, and the agent runtime;
they differ in what drives the loop.

- **Build mode** — the user describes a project; the harness decomposes, staffs, and runs it
  to completion. Finishes. Described in §1–§16.
- **Maintenance mode** — a continuous, cron-shaped loop that watches one or more repos,
  triages incoming issues against the mission, and keeps the board current. Never finishes.
  Described in §17.6.

A single project may be in build mode initially and transition to maintenance mode once no
tasks remain open. This is a mode flag on the project, not two separate systems.

---

## 14. Phased delivery

**Phase 0 — Judge layer (no UI).**
Rubric files, `judge.py`, shortlist-in-code, one-request-per-subject, the audit table.
Prove §13.10 on fixtures. *This is already partly done: `~/.hermes/cache/scratch/jev_score_truth.py`.*

**Phase 1 — Scheduler + store.**
State machine, DAG, checkpoints, budgets, ledger, retry ladder. Tested with a fake agent
that returns scripted outcomes. No LLM, no Jev beyond the seams already proven.

**Phase 2 — Planning.**
Decomposition via LLM, `dod_quality` gate, agent proposal from live roster, cost estimate.
Dry run end-to-end.

**Phase 3 — Agent runtime.**
Real delegation. Concurrency, budgets, kill switch, transcript capture.

**Phase 4 — UI.**
Four screens. Board, drawers, kill switch, final report.

**Phase 5 — Autonomy tuning.**
Escalation ladder, assumption ledger, intervention-rate measurement, threshold re-tuning
against real runs.

---

## 15. Decisions made (outstanding questions, resolved)

Where the request was silent, these are the calls I made — each reversible.

1. **Storage:** SQLite + git-backed work dirs. No external services. Survives a restart.
2. **Hosting:** local FastAPI, bound to localhost and the Tailscale interface. No cloud, no auth beyond network locality.
3. **The board never blocks on one task.** Park-and-continue is the default, not halt.
4. **Assumptions are the primary answer to "no input".** Decide, log, report, revert.
5. **Approval covers the plan, not just the team.** Decomposition and DoDs are where
   delegation actually fails; approving only the agent list approves the wrong thing.
6. **The gate is a 3-rung action band; the report is a 10-rung artifact scale.** Both in
   one request. Gate decisions; report numbers.
7. **0–10 is not literally expressible.** The API caps Scores at 10 levels; the report
   ladder has 10 rungs and is normalised to 0–10 for display.
8. **Rubrics are versioned files, and thresholds live with them.** Measured ladder-dependence
   (6.69 vs 3.73 for the same state) makes cross-rubric comparison unsafe.
9. **`max_attempts = 3`, `max_concurrent = 3`.** Conservative defaults; both configurable.
10. **Agents are proposed from a live roster, never hardcoded.** Roster changes must not
    require a prompt change.
11. **Jev is pinned** (`jev-1.13.0`), and the response's reported `model` field is recorded,
    so a silent upgrade cannot invalidate tuned thresholds unnoticed.
12. **Intervention rate is a first-class metric.** "No input ideally" is only meaningful if
    it's measured.

---

## 17. Annex — GitHub Projects as an optional interface

**Status:** Proposed, optional, off by default. Nothing in §1–§16 depends on it.

### 17.1 Design rule: mirror, not source of truth

The local SQLite store remains authoritative. GitHub is a **one-way projection plus a
human-collaboration surface**. The run loop never blocks on GitHub, never reads GitHub to
decide its next action, and never mutates local state from a GitHub read except through the
explicit override path in §17.5.

Rationale beyond rate limits:

- **No transaction semantics.** §10 requires every transition to be atomic with a
  checkpoint. GitHub offers no transaction; a crash mid-write leaves the mirror stale.
  Local-first turns that into a reconciliation job instead of a correctness bug.
- **Judgment payloads must not leave the machine.** `judgment` rows carry raw agent output.
  Only the derived **band** and **score** cross the boundary — never the request body.
- **Failure isolation.** A GitHub outage or auth expiry degrades the mirror, not the board.
- **Write latency.** Every call is a network round trip; inline on the critical path it
  slows the loop for no benefit.

### 17.2 Measured cost (live probe, 2026-09-20, token scope `project`)

Operational rule: **event-driven, never polling.**

GraphQL point cost, 5,000 points/hr/user budget:

| Operation | Points |
|---|---|
| Number field write (score) | 1 |
| Single-select write (band) | 1 |
| Issue create | 1 |
| Board read, 5 items w/ fields | 6 |
| Board read, 20 items w/ fields | **102** |
| Project field-list read | **102** |
| Full tick (20 tasks × 2 writes + 1 read) | 142 (3.46/transition) |

**Writes are cheap; reads are not.** Board reads are N+1 (~5 points/item). A 100-item board
read costs ~500 points — polling it every 10 seconds exhausts the hourly budget in under
four minutes. A 100-task project with ~5 transitions each costs ~500 points total, so
**write volume is a non-issue; read volume is the only real constraint.**

Consequences:
- Push on transition. Batch all writes for one scheduler tick into one flush.
- Read only on explicit user action or a post-run reconcile, never in the loop.
- Token bucket sized at **≤2,000 points/hr** for sync; on exhaustion, sync pauses and the
  board keeps running. GitHub is never allowed to stall the scheduler.

### 17.3 Field mapping

| Harness | GitHub | Direction |
|---|---|---|
| `project.title` | Project title | write |
| `project.description` | Project README | write |
| `task` | Issue (or draft item if no repo) | write on create |
| `task.parent_id` | Sub-issue relationship | write |
| `edge.kind = blocks` | Native blocked-by dependency | write |
| `task.state` | Status single-select: Queued / Running / Blocked / Needs Input / Review / Done / Failed | write + **human override** |
| `task.success_band` | `JevBand` single-select: rework / complete / harvest | write only (§17.5) |
| `task.success_score` | `JevScore` number 0–10 | write only (§17.5) |
| `task.attempt` | `Attempts` number | write only |
| `task.model_tier` | `Tier` single-select | write only |
| `question` | Issue comment tagged `<!-- jev:question -->` | write |
| `assumption` | `Assumption` checkbox + comment | write |
| run cost | `Cost` number (USD) | write only |
| — | Labels: `jev:managed`, `jev:needs-info`, `jev:spam` | write |

Native sub-issues and blocked-by give the DAG visualization for free — tasks as issues,
subtasks as sub-issues, `blocks` edges as dependencies.

### 17.4 Sync architecture

- **Outbox.** Every local transition appends a `sync_outbox` row in the same transaction as
  the state change. A background flusher drains it. Crash-safe by construction: the outbox
  row and the transition commit together.
- **Idempotency.** Each outbox row carries a deterministic key
  (`task_id:attempt:transition`); replay is a no-op.
- **Reconcile.** On startup and on demand, compare local state to the mirror by a stored
  `github_id` + `github_updated_at` per record. Divergence is reported, not auto-resolved.
- **Secrets.** GitHub token read from the environment only, never persisted in project config.

### 17.5 Conflict precedence

The one rule that must not be got wrong:

- **Human edits to `Status` win.** A human dragging a card is the authority. The harness
  reflects it into the local store as an audited `override` row (who, when, from, to), then
  proceeds from the new state. This is the *only* path by which GitHub mutates local state.
- **The harness exclusively owns `JevBand`, `JevScore`, `Attempts`, `Cost`.** These are
  computed outputs of judgments. A human edit is overwritten on the next tick and the
  overwrite is logged. Nobody hand-edits a score and has it stick.
- **Label and title edits are advisory.** Recorded, never acted on.

### 17.6 Issue triage (maintenance mode)

An issue is an **external request for work** — untrusted input, same treatment as any other.
It is **not** automatically a task: two issues may be one task, one issue may be five.

**Intake chain** (each step may terminate the flow):

1. **Spam gate** (deterministic first: author allowlist, age, rate; then Jev `spam_likelihood`).
   Fails → label `jev:spam`, no board entry.
2. **`issue_actionable`** (Noul): is this a request for work at all?
3. **`issue_mapping`** (Choice): `new_task` / `append_existing` / `split` / `needs_info` /
   `not_actionable`. Shortlist candidate existing tasks in code (semantic similarity), then
   judge — never a Choice over the whole backlog.
4. **`dod_quality`** on the derived DoD — an issue that cannot be restated testably parks as
   `needs-info` rather than being delegated.
5. **`context_relevance`** against the mission statement: in scope, adjacent, or out of scope.

**Every outcome produces a comment**, including rejection — a triage comment explaining
*why not* is genuine value, not a dead end. Parked issues get a `jev:needs-info` label and a
question, and re-enter the chain when answered.

**Critical constraint:** an issue can never trigger a destructive or external-effect action.
The §7.3 authority ceiling applies with no exceptions for externally-authored input.

### 17.7 Mission state

Maintenance mode needs a persistent statement of intent to triage against:

```
mission(id, text, constraints, updated_at)
```

The mission is proposed at project creation, editable in the UI, and versioned — triage
judgments record `mission_version`, so a mission edit does not silently invalidate prior
triage decisions.

### 17.8 UI

When sync is enabled, Screen 4 gains an **Open in GitHub** link and a sync-status indicator
(last push, outbox depth, points spent this hour, last reconcile). The native UI remains
fully functional with sync off — GitHub is additive, never required.

### 17.9 Acceptance criteria (annex)

- With sync off, the system behaves exactly as specified in §13.
- A crash between a local transition and its flush reconciles on restart with no duplicate
  or lost transition (idempotent outbox).
- Sync exhaustion never stalls the scheduler.
- No `judgment.request_json` field ever crosses the network boundary.
- A human `Status` edit becomes an audited override; a human `JevScore` edit is overwritten
  and the overwrite logged.
- An issue that fails the spam gate produces no board entry and no `new_task`.
- An issue-derived DoD that fails `dod_quality` parks as `needs-info`, and never reaches an
  agent.

---

## 18. Explicitly deferred

- Multi-project scheduling and shared agent pools
- Learned thresholds (fit ECE against labelled runs) — calibration work, Stage 2
- Inter-agent messaging / negotiation protocol
- Mobile approvals
- Rubric auto-tuning
- Bidirectional GitHub live sync (GitHub → local beyond the §17.5 override path)
- GitHub PR review as a verification signal (PR-as-artifact is a natural follow-on)
- Multi-repo / org-level boards
