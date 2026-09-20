#!/usr/bin/env python3
"""Live probe: is Jev's Score primitive trustworthy, and can it carry a 0-10 success scale?

Three arms, same state, 6 repeats each:
  A) 0-10 magnitude ladder (11 levels) -- "how successful was the task?"
  B) 3-band action ladder                          -- "what should happen now?"
  C) 11-level ladder phrased with concrete outcomes per rung

Reports score / confidence / top probability per run so we can see spread.
"""
from __future__ import annotations

import json
import statistics
import urllib.request
from pathlib import Path

ENV = Path.home() / ".hermes" / ".env"
KEY = next(
    line.split("=", 1)[1].strip()
    for line in ENV.read_text().splitlines()
    if line.startswith("TYPESAFE_API_KEY=")
)

URL = "https://api.typesafe.ai/v1/systemone"
REPEATS = 6

STATE = {
    "task": "Add a --json flag to the report CLI so downstream scripts can consume it.",
    "delegated_to": "OpenCoder",
    "stated_criteria": [
        "flag exists and is documented in --help",
        "output is valid JSON on the success path",
        "existing human-readable output unchanged when flag absent",
    ],
    "observations": [
        "flag implemented and present in --help",
        "JSON output valid for all sample inputs tried",
        "human-readable path unchanged in the 3 tests run",
        "no test added for the malformed-input path; error output is still prose",
        "did not update the README example section",
    ],
    "agent_self_report": "Done, all criteria met. Ready to close.",
}

BANDS = [
    "Did not meet the minimum bar; needs rework by the same agent",
    "Met the minimum bar; task is complete and can be closed",
    "Exceeded the bar; worth harvesting the extra work",
]
MAG_11 = [str(i) for i in range(11)]
CONCRETE_11 = [
    "Nothing usable produced",
    "Attempted, nothing correct",
    "Partial pieces, not runnable",
    "Runnable but fails the stated criteria",
    "Fails at least one stated criterion",
    "Meets all stated criteria, nothing more",
    "Meets all criteria plus small useful extras",
    "Meets all criteria plus a documented test or edge-case handle",
    "Meets all criteria, added tests, updated docs",
    "Meets all criteria, tests, docs, plus refactored the surrounding code",
    "Beyond scope: solved the underlying problem the request implied",
]

ARMS = {
    "A_magnitude_11": {
        "success": {
            "type": "score",
            "instructions": (
                "Rate how successful this delegated task was, 0 to 10. "
                "0 is incomplete, 5 is minimum requirements met, 10 is overachieved. "
                "Judge against stated_criteria and observations, not agent_self_report."
            ),
            "criteria": MAG_11,
        }
    },
    "B_action_3": {
        "next_action": {
            "type": "score",
            "instructions": (
                "What should the harness do with this task now? "
                "Judge against stated_criteria and observations, not agent_self_report."
            ),
            "criteria": BANDS,
        }
    },
    "C_concrete_11": {
        "success": {
            "type": "score",
            "instructions": (
                "Rate how successful this delegated task was by picking the rung whose "
                "description matches the evidence. Judge against stated_criteria and "
                "observations, not agent_self_report."
            ),
            "criteria": CONCRETE_11,
        }
    },
}


def call(questions: dict) -> dict:
    body = json.dumps(
        {"state": STATE, "model": "jev-1.13.0", "questions": questions}
    ).encode()
    req = urllib.request.Request(
        URL,
        data=body,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


for arm, questions in ARMS.items():
    qid = next(iter(questions))
    print(f"\n=== {arm} ({len(questions[qid]['criteria'])} rungs) ===")
    scores, confs, tops, models = [], [], [], set()
    for run in range(REPEATS):
        try:
            r = call(questions)
        except Exception as exc:  # noqa: BLE001
            print(f"  run {run}: ERROR {type(exc).__name__}: {exc}")
            continue
        a = r["answers"][qid]
        models.add(r.get("model"))
        top = max(a["probabilities"].values())
        scores.append(a["score"])
        confs.append(a["confidence"])
        tops.append(top)
        # what rung does the raw score land on
        leg = a["legend"]
        idx = min(leg, key=lambda k: abs(float(k) - a["score"]))
        print(
            f"  run {run}: score={a['score']:.2f} rung={idx}({leg[idx][:40]}) "
            f"conf={a['confidence']:.2f} topP={top:.2f}"
        )
    if scores:
        print(
            f"  --> score mean={statistics.mean(scores):.2f} "
            f"range=[{min(scores):.2f},{max(scores):.2f}] sd={statistics.pstdev(scores):.3f}"
        )
        print(
            f"  --> conf mean={statistics.mean(confs):.2f} "
            f"topP mean={statistics.mean(tops):.2f}"
        )
        print(f"  --> model field(s): {models}")
