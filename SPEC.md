# Jev Task Harness — Specification v0.2

**Status:** Draft for review
**Author:** Hermes Agent (Link)
**Date:** 2026-09-21
**Scope:** A self-hosted, single-user system that takes a project description, proposes an
agent team, and then runs a kanban board to completion with minimal human input.

v0.2 rewrites v0.1 to narrow the scope. What changed, and why:

- The interface is a **locally hosted HTML dashboard** (§9). There is no other UI.
- **No other harness.** The system is self-contained — its own store, its own scheduler,
  its own loop (§1, §3). It is not built on or driven by Hermes, OpenCoder, or any other
  agent framework.
- **No GitHub Projects, and no external task board.** All GitHub integration is removed,
  including maintenance mode and issue triage (§18.1). An external board would need an
  identity per agent and offers no transactions.
- Everything else — the judge layer, the seams, the rubrics, the lifecycle, the autonomy
  policy — is carried over from v0.1 unchanged. The numbers measured against `jev-1.13.0`
  still hold.

---

## 1. Purpose and scope

Give one person a system where they describe a large project once, approve a starting
configuration once, press **Go**, and walk away. The system decomposes the work, staffs
it, schedules it, supervises it, verifies results against stated criteria, and reports a
quantitative success score back.

### 1.1 Scope statement

This is the whole system:

- **One process.** A single Python application. It serves the dashboard, runs the
  scheduler loop, and holds the store.
- **One store.** A single SQLite file, plus one directory of git-backed work products.
  No database server, no message broker, no cache.
- **One interface.** A locally hosted HTML dashboard served by that process (§9). Static
  files, no build step, no package manager, no external asset host.
- **One external dependency.** Network access to the judge API (§5). Everything else runs
  on the machine.

A machine with Python, the harness directory, and network access to the judge API can run
the whole system. Nothing else needs to be installed, configured, or kept running.

### 1.2 Non-goals

- **Not a plugin, wrapper, or extension of any existing agent framework.** It does not
  require Hermes, does not depend on Hermes Kanban, and does not delegate its own loop to
  another agent. It is a standalone harness with its own store, its own scheduler, and its
  own state machine. If it is ever convenient to *drive* it from another system, that
  system is a client of its API and nothing more.
- **Not built on a pre-existing task board, and not mirrored to one.** The task graph,
  claim semantics, checkpoints, and audit log are specified here and implemented here
  (§3–§4, §10). The board is rendered by the local dashboard. There is no GitHub Projects
  integration, no issue tracker integration, and no import of any external board's schema
  or semantics — see §18.1 for why this was removed.
- **Not multi-tenant.** Single user, single machine, no auth beyond network locality.
- **Not a chat interface.** The user is not a co-pilot; the system is expected to run
  unattended.
- **Not a general agent framework.** It orchestrates *this* machine's agents on *this*
  user's projects.
- **Not a replacement for human judgement on consequential actions.** It never escalates
  its own authority (§7.3).

### 1.3 Interoperability boundary

The system is closed by default. Two integrations are permitted, and both are edges, not
substrate:

- **Agent subprocesses.** The harness spawns delegated agents itself, as child processes it
  owns, supervises, and terminates. Which CLI or framework that subprocess happens to be is
  a runtime detail (§3); the loop, the state machine, and the store stay here.
- **A read-only client API.** Another system may call this API to observe or drive a run.
  It gets no special access: it is a client, with the same surface as the dashboard.

Nothing else crosses the boundary. There is no sync, no mirror, no webhook, and no
external identity.

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
│  Dashboard  (locally hosted HTML, single page)               │
│   static files served by this same process                   │
│   Screen 1: Project · Screen 2: Settings · Screen 3: Team    │
│   Screen 4: Board (live)                                     │
└───────────────────────────┬──────────────────────────────────┘
                            │ HTTP (localhost / tailnet only)
┌───────────────────────────▼──────────────────────────────────┐
│  API  (FastAPI)                                              │
│   /project /config /plan /board /runs /audit /kill           │
│   also serves the dashboard's static files                   │
└───────┬──────────────────┬──────────────────┬────────────────┘
        │                  │                  │
┌───────▼───────┐  ┌───────▼────────┐  ┌──────▼───────────────┐
│  Scheduler    │  │  Judge Layer   │  │  Agent Runtime       │
│  (DAG, queues │  │  judges/       │  │  (spawns delegated   │
│   concurrency │  │   *.json       │  │   agents as child    │
│   budgets)    │  │  judge.py      │  │   processes)         │
└───────┬───────┘  └───────┬────────┘  └──────┬───────────────┘
        │                  │                  │
┌───────▼──────────────────▼──────────────────▼────────────────┐
│  Store: SQLite (board, runs, judgments, ledger)              │
│  + Git-backed work dirs (agent artifacts, checkpoints)       │
└──────────────────────────────────────────────────────────────┘
```

The box labelled **Dashboard** is static HTML/CSS/JS on disk, served by the API process.
There is no separate frontend build, dev server, or bundler.

**Components**

- **Dashboard** — four screens of static HTML driven by `fetch` against the local API; the
  only human surface. Same-origin with the API, so no CORS, no tokens, no session state.
  Local-only binding; reachable over Tailscale.
- **API** — thin. All mutations go through the scheduler. Also the static file server for
  the dashboard.
- **Scheduler** — the state machine. Owns the DAG, ready-queue, concurrency slots,
  budget ledger, retry ladder, and checkpointing.
- **Judge Layer** — wraps Jev. Loads versioned rubric files, shortlists candidates in code,
  makes one request per subject, records the raw answer + rubric version + model version.
- **Agent Runtime** — spawns delegated agents as child processes of this harness. Each
  agent is a bundle of `{prompt, model, toolset, workdir, budget}`. Its adapts to whatever
  delegation target is configured; the harness does not care which, and does not depend on
  any of them being present to start.
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
override(id, entity_type, entity_id, field, from_value, to_value, actor,
         source, created_at)                                     -- §7.5 (dashboard edits)
```

**Field glossary** (fields whose names were previously used without definition)

- `task.state` — the seven kanban states, exactly: `queued`, `running`, `blocked`,
  `needs_input`, `review`, `done`, `failed`. The §10 pipeline is the *project* lifecycle and
  uses different names (`DRAFT`…`COMPLETE`); the two are deliberately separate vocabularies.
- `task.success_band` — the categorical gate outcome from `acceptance_verdict`: `rework`,
  `complete`, or `harvest`.
- `task.success_score` — the 0–10 report value from `success_score`, carrying
  `judgment.rubric_version`. Never comparable across rubric versions (§6).
- `task.reversibility` — one of `read_only`, `reversible`, `destructive`, `external_effect`,
  produced by the `reversibility` seam. Feeds the §7.1 escalation ladder.
- `task.blast_radius` — the scope a failed attempt can affect; `task` | `project` | `external`.
- `override.source` — where the human edit came from. In this version there is exactly one
  value, `dashboard`. It exists as an enumerated field (not a boolean) so a future client
  can be added without a migration.

**Invariants**

- A task's `state` is mutated only by the scheduler, and only via an explicit transition
  table.
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
| ★ | `dod_quality` | Choice (+ `none`) | Reject untestable DoDs before they reach the board |
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

**Second rubric**, `dod_quality@1.json`. Same shape as above — `id`, `type`, `instructions`,
`criteria` — and it gates DoDs before they reach the board.

```json
{
  "version": "dod_quality@1",
  "rubric": {
    "id": "dod_quality",
    "type": "choice",
    "instructions": "Does this task's definition of done describe something that can be objectively verified as met or not met? Choose none if it is adequately testable.",
    "criteria": {
      "untestable": "Cannot be objectively checked; success is a matter of opinion",
      "unmeasurable": "Describes a goal with no observable completion condition",
      "circular": "Verification depends on the thing being verified",
      "contradicts_constraints": "Cannot be satisfied without violating a stated project constraint",
      "implementation_specified": "Prescribes a method rather than specifying an outcome",
      "none": "Adequately testable as written"
    }
  }
}
```

**File contract for every rubric file**

- `version` — the filename stem verbatim, e.g. `success_scale@1`. Recorded on every
  `judgment` row. A rubric edit **must** bump the version; thresholds are stored alongside
  the version and re-tuned when it changes (§6 measured property 4).
- `rubric.id` — the seam name this rubric serves (§5). One rubric file per gated seam.
- `rubric.type` — `choice`, `noul`, or `score`.
- `rubric.criteria` — for `choice`, a map of option → description, and it **must** include a
  `none` (or `unknown`) option so "no match" is measurable rather than forced.
- Code generates the Choice criteria sent to Jev from this file. Prose documentation is
  derived from it, never authored separately — three copies drift.
- A rubric file is the unit of review: changing one is a reviewable diff, and the
  `rubric_versions_json` on the project config pins which versions a run used.

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

### 7.5 Human edits from the dashboard

The dashboard is the only human surface, so it is also the only source of `override` rows.
The precedence rule:

- **Human edits to `task.state` win.** The scheduler reflects the edit into the store as an
  audited `override` row (who, when, from, to) and proceeds from the new state.
- **The harness exclusively owns `success_band`, `success_score`, `attempt`, and run cost.**
  These are computed outputs of judgments. A human edit is overwritten on the next tick and
  the overwrite is logged.

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

## 9. Dashboard (the local HTML interface)

The human interface is a **locally hosted HTML dashboard**. That is a hard constraint, not
a placeholder for a "real" UI later.

**What "locally hosted HTML" means here:**

- Static `.html`, `.css`, and `.js` files on disk, in the repo, served by the same process
  as the API. Same origin, so no CORS configuration and no auth token.
- **No build step.** No bundler, no transpiler, no package manager, no framework. If a file
  has to be compiled before the browser sees it, it is out of scope.
- **No external assets.** No CDN, no web fonts, no analytics, no third-party script. The
  page works on a machine with no internet access once loaded; the only network calls it
  makes are to its own API.
- Data flows by `fetch` against the local API and by a polling loop or Server-Sent Events
  for live updates. No websocket library dependency.

**The four screens.** Every screen is read-mostly; only screens 1–3 accept input.

### Screen 1 — Project

- Title (short), Description (long, free text), Constraints (optional free text)
- Attachments: links to repos, directories, docs
- **Nothing else.** No agent configuration on this screen.

### Screen 2 — Settings

- **Model roster**: rows of `{label, provider, model_id, tier(cheap|mid|frontier),
  cost_per_mtok_in, cost_per_mtok_out, toolset, enabled}`. This is the *only* place
  models are configured; the roster is what the `agent_selection` shortlist draws from.
  It is a local file/database list — no external model registry, no account linking.
- **Budgets**: tokens, USD, wall clock, max concurrent.
- **Autonomy**: policy (`default` | `strict`), assumption limit, question batching window.
- **Judge**: Jev model id (pinned, e.g. `jev-1.13.0`), rubric versions, review threshold.
- Settings persist as a named `config`; a project references one.

### Screen 3 — Team proposal

- **Decomposition panel**: the proposed task list as a DAG, each task showing its DoD and
  the assigned agent. Flagged items from `dod_quality` are highlighted with the reason.
- **Team panel**: proposed agents, each with role, model, toolset, and the Jev
  `capability_fit` score that justified it. Agents are proposed from the configured roster —
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
- **Assumptions drawer**: every rung-1 decision, individually revertible
- **Kill switch**, always visible
- **Final report**: on completion, a per-task success score (0–10), the band, every
  assumption, every escalation, total cost, and the intervention rate. Exportable as
  Markdown.

The board is rendered from the local store. It is never a projection of, or a mirror to,
anything external (§18.1).

---

## 10. Run lifecycle (state machine)

```
DRAFT ──▸ PLANNING ──▸ PROPOSED ──▸ GO ──▸ RUNNING ⇄ PARKED
                                             │
                                             ├─▸ REVIEWING ──▸ CLOSING ──▸ COMPLETE
                                             └─▸ FAILED ──▸ (attribution) ──▸ retry | respec | park
```

Transitions are a hard-coded table. Checkpoint after every transition: on restart the board
resumes at the last transition, and completed work is never redone (idempotent by
`task_id` + `attempt`).

**The transition table.** This is the authoritative list. Any transition not in it is a bug,
not a policy question. "Cause" names what fired the transition.

| From | To | Cause | Guard |
|---|---|---|---|
| `queued` | `running` | scheduler dispatch | concurrency slot free ∧ budget OK ∧ deps satisfied ∧ not `dry_run` |
| `queued` | `blocked` | dependency not satisfied | any inbound `blocks` edge unresolved |
| `running` | `review` | agent returned | result artifact written |
| `running` | `blocked` | `status_classification` = blocked | — |
| `running` | `needs_input` | `escalate_to_human` = park | question row written |
| `running` | `failed` | run error, or `loop_breaker` fired | — |
| `blocked` | `queued` | inbound deps resolved | checkpoint flush |
| `needs_input` | `queued` | question answered | rung-4 authorization present if `destructive` |
| `review` | `running` | `acceptance_verdict` = `rework` | `attempt` < `max_attempts` |
| `review` | `done` | `acceptance_verdict` = `complete` or `harvest` | success_score + band recorded |
| `review` | `needs_input` | `criterion_failed` needs a human decision | — |
| `review` | `queued` | task re-specified (`bad_spec` recovery) | new `dod_json` written |
| `failed` | `queued` | recovery path selected, retry permitted | `attempt` < `max_attempts` ∧ recovery ≠ park |
| `failed` | `needs_input` | recovery = park (`environment`) | question row written |
| `failed` | `queued` (new subtree) | recovery = re-decompose | parent task replaced |
| `done` | `queued` | human override from the dashboard (§7.5) | `override` row written; reopening by the harness is a new task, not a transition |

**Terminal states.** `done` and `failed` are terminal *for the harness*. The only thing that
can move them is a human edit from the dashboard (§7.5), which is recorded as an `override`
row and is by construction outside the loop. No seam, no retry ladder, and no agent can move
a task out of `done` or `failed`.

**Project lifecycle** (`§10` diagram) is `DRAFT → PLANNING → PROPOSED → RUNNING ⇄ PARKED →
REVIEWING → CLOSING → COMPLETE`, with `FAILED → attribution → retry | respec | park`. Task
states and project states are separate vocabularies (§4 glossary).

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
- `success_score` is only reported with its rubric version attached.
- A run is fully reconstructible offline from `judgment` + `run` + `ledger`.
- Structured logs, one line per transition: `ts, task_id, from, to, cause, judgment_id`.
- The audit view answers: *why did this task get this agent, this score, this decision?*
- The audit view is a screen in the local dashboard, reading the local store. It needs no
  external service to answer that question.

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
    sd ≤ 0.10 normalised, gate stability (0 label flips across 3 repeats).
11. Quality gates: `ruff`, `mypy --strict`, `pytest` green before any commit.
12. **Self-containment:** a fresh clone plus Python plus a judge API key runs the full
    system with no other framework installed, no GitHub token, and no external board.
    The dashboard loads and functions with the machine's network cable pulled (the only
    degraded function being judge calls).
13. **No external identity:** no code path in the harness requires an account, token, or
    identity for any agent, on any external service.

---

## 14. Operating modes

The harness shape is one mode. v0.1 described a second (`maintenance`) and an annex that
implemented it; both are removed (§18.1). What remains:

- **Build mode** — the user describes a project; the harness decomposes, staffs, and runs it
  to completion. Finishes. This is the whole of this version.

A future maintenance loop is not designed here. If it returns, it returns on the same
judge layer and the same store, driven by a local scheduler tick — not by an external
tracker, and not requiring an identity per agent.

---

## 15. Phased delivery

Phase 1 is the scheduler and store, built here, from scratch. There is no framework to
introduce and no board to wrap: §3–§4 and §10 are the design, and they are the whole of the
component. A general-purpose task board on the host machine is *not* an input to any phase.

**Phase 0 — Judge layer (no UI).**
Rubric files, `judge.py`, shortlist-in-code, one-request-per-subject, the audit table.
Prove §13.10 on fixtures. *This is already partly done: `probes/jev_score_truth.py`.*

**Phase 1 — Scheduler + store.**
State machine, DAG, checkpoints, budgets, ledger, retry ladder. Tested with a fake agent
that returns scripted outcomes. No LLM, no Jev beyond the seams already proven.

**Phase 2 — Planning.**
Decomposition via LLM, `dod_quality` gate, agent proposal from the configured roster, cost
estimate. Dry run end-to-end.

**Phase 3 — Agent runtime.**
Real delegation as owned subprocesses. Concurrency, budgets, kill switch, transcript capture.

**Phase 4 — Dashboard.**
Static HTML. Four screens. Board, drawers, kill switch, final report. Served by the API
process; no build step, no external assets.

**Phase 5 — Autonomy tuning.**
Escalation ladder, assumption ledger, intervention-rate measurement, threshold re-tuning
against real runs.

---

## 16. Decisions made (outstanding questions, resolved)

Where the request was silent, these are the calls made. Each is reversible.

1. **Storage:** SQLite + git-backed work dirs. No external services. Survives a restart.
2. **Hosting:** local FastAPI, bound to localhost and the Tailscale interface. No cloud, no
   auth beyond network locality. The same process serves the dashboard's static files.
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
10. **Agents are proposed from a configured roster, never hardcoded.** Roster changes must
    not require a prompt change.
11. **Jev is pinned** (`jev-1.13.0`), and the response's reported `model` field is recorded,
    so a silent upgrade cannot invalidate tuned thresholds unnoticed.
12. **Intervention rate is a first-class metric.** "No input ideally" is only meaningful if
    it's measured.
13. **The interface is plain locally hosted HTML.** No build step, no framework, no CDN.
    Chosen for durability and reviewability over convenience (§9).
14. **No external board, no agent identities.** The board is local SQLite; nothing about the
    harness requires an account on any external service (§18.1).

---

## 17. Explicitly deferred

- Multi-project scheduling and shared agent pools
- Learned thresholds (fit ECE against labelled runs) — calibration work, Stage 2
- Inter-agent messaging / negotiation protocol
- Mobile approvals
- Rubric auto-tuning
- A maintenance loop driven by a local scheduler tick over a watched repo
- Any external board, mirror, or issue-tracker integration

---

## 18. Removed from v0.1

### 18.1 GitHub Projects integration (whole annex) — removed

v0.1 carried a GitHub Projects annex: a one-way mirror of the local board, a field mapping,
an outbox with idempotency keys, a conflict-precedence rule for human `Status` edits, a
GraphQL rate-budget, and a maintenance-mode issue-triage chain.

It is **removed entirely** in v0.2. The reasons, in order of weight:

- **It requires an identity for every agent.** A mirror means each agent's work must be
  attributable to a GitHub actor. That pulls account provisioning, tokens, and a
  per-agent auth surface into a system whose stated scope is one user on one machine.
- **It is an external dependency for a board that does not need one.** The dashboard
  renders the board from local SQLite with no round trip, no rate limit, and no outage
  mode. Mirroring adds a second source of truth to keep reconciled.
- **No transaction semantics.** The v0.1 spec already admitted this: a crash mid-write
  leaves the mirror stale, turning a correctness property into a reconciliation job. A
  local-only board has no such window.
- **It widens the scope the user asked to narrow.** §1 defines the system as one process,
  one store, one interface. That is now literally true.

Removed with the annex: `sync_outbox` (dropped from §4), the `github_id` /
`github_updated_at` reconcile fields, the `JevBand` / `JevScore` / `Attempts` / `Cost`
field-mapping rationale in §7.5, the `gh_cost_clean.sh` probe and its README section,
`maintenance` mode (§14), the mission entity, and every §17 reference in the acceptance
criteria. The `override` entity survives (§4, §7.5) because the dashboard needs it; only
its GitHub source is gone.
