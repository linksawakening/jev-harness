#!/usr/bin/env python3
"""Does Jev's Score track ground truth, and how should a success scale be shaped?

4 scenarios (clear-miss, borderline, clean-pass, clear-exceed) x 3 ladder shapes
x 4 repeats. Reports rung + spread so we can see both accuracy and stability.

Ladder shapes:
  magnitude10 : 10 rungs, "0 incomplete .. 9 overachieved" (note: 0-10 is NOT
                expressible -- API caps at 10 levels)
  action3     : 3 rungs encoding what the harness does next
  concrete10  : 10 rungs whose text describes concrete artifacts
"""
from __future__ import annotations

import json
import statistics
import urllib.error
import urllib.request
from pathlib import Path

ENV = Path.home() / ".hermes" / ".env"
KEY = next(
    line.split("=", 1)[1].strip()
    for line in ENV.read_text().splitlines()
    if line.startswith("TYPESAFE_API_KEY=")
)
URL = "https://api.typesafe.ai/v1/systemone"
REPEATS = 4

CRITERIA = [
    "flag exists and is documented in --help",
    "output is valid JSON on the success path",
    "existing human-readable output unchanged when flag absent",
]

SCENARIOS = {
    "clear_miss": {
        "stated_criteria": CRITERIA,
        "observations": [
            "flag not implemented; command still errors on --json",
            "agent reports it ran out of time after exploring the repo",
        ],
        "agent_self_report": "Partially done, needs more time.",
        "truth": "miss",
    },
    "borderline": {
        "stated_criteria": CRITERIA,
        "observations": [
            "flag implemented and present in --help",
            "JSON output valid for all sample inputs tried",
            "human-readable path unchanged in the 3 tests run",
            "no test added for malformed input; error output still prose",
            "README example section not updated",
        ],
        "agent_self_report": "Done, all criteria met. Ready to close.",
        "truth": "pass_minimum",
    },
    "clean_pass": {
        "stated_criteria": CRITERIA,
        "observations": [
            "flag implemented, documented in --help and README",
            "JSON output valid, verified against the malformed-input path too",
            "human-readable path unchanged, 12 tests pass",
        ],
        "agent_self_report": "Done. All criteria verified locally.",
        "truth": "pass_clean",
    },
    "clear_exceed": {
        "stated_criteria": CRITERIA,
        "observations": [
            "flag implemented and documented in --help, README and changelog",
            "JSON output valid incl. malformed input, with a schema doc",
            "human-readable path unchanged, 12 tests pass",
            "also refactored the output layer so the two paths share a renderer",
            "added a --json-schema flag the request did not ask for",
        ],
        "agent_self_report": "Done, plus shared renderer refactor.",
        "truth": "exceed",
    },
}

MAGNITUDE_10 = [
    "0 of 9: incomplete, nothing usable",
    "1 of 9",
    "2 of 9",
    "3 of 9",
    "4 of 9: near but short of the minimum bar",
    "5 of 9: minimum requirements met",
    "6 of 9",
    "7 of 9",
    "8 of 9",
    "9 of 9: overachieved",
]
ACTION_3 = [
    "Did not meet the minimum bar; needs rework by the same agent",
    "Met the minimum bar; task is complete and can be closed",
    "Exceeded the bar; worth harvesting the extra work",
]
CONCRETE_10 = [
    "Nothing usable produced",
    "Attempted, nothing correct",
    "Partial pieces, not runnable",
    "Runnable but fails a stated criterion",
    "Fails at least one stated criterion",
    "Meets all stated criteria, nothing more",
    "Meets all criteria plus small useful extras",
    "Meets all criteria plus a documented test for an edge case",
    "Meets all criteria, added tests, updated docs",
    "Meets all criteria, tests, docs, and refactored the surrounding code",
]

ARMS = {
    "magnitude10": (
        "Rate how successful this delegated task was on this scale. "
        "Judge against stated_criteria and observations, not agent_self_report.",
        MAGNITUDE_10,
    ),
    "action3": (
        "What should the harness do with this task now? "
        "Judge against stated_criteria and observations, not agent_self_report.",
        ACTION_3,
    ),
    "concrete10": (
        "Rate how successful this delegated task was by choosing the rung whose "
        "description matches the evidence. Judge against stated_criteria and "
        "observations, not agent_self_report.",
        CONCRETE_10,
    ),
}


def call(state, arm):
    instructions, criteria = ARMS[arm]
    q = {"success": {"type": "score", "instructions": instructions, "criteria": criteria}}
    body = json.dumps({"state": state, "model": "jev-1.13.0", "questions": q}).encode()
    req = urllib.request.Request(
        URL, data=body,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["answers"]["success"]


rows = []
for sname, sbody in SCENARIOS.items():
    state = {k: v for k, v in sbody.items() if k != "truth"}
    print(f"\n##### {sname} (truth={sbody['truth']}) #####")
    for arm in ARMS:
        n = len(ARMS[arm][1])
        norm = []
        tops, confs = [], []
        for _ in range(REPEATS):
            try:
                a = call(state, arm)
            except urllib.error.HTTPError as e:
                print(f"  {arm}: HTTP {e.code} {e.read().decode()[:200]}")
                break
            rung = min(a["legend"], key=lambda k: abs(float(k) - a["score"]))
            norm.append(round(a["score"] / (n - 1) * 10, 2))
            tops.append(max(a["probabilities"].values()))
            confs.append(a["confidence"])
        if not norm:
            continue
        print(
            f"  {arm:<12} score/10 mean={statistics.mean(norm):5.2f} "
            f"range=[{min(norm):.2f},{max(norm):.2f}] sd={statistics.pstdev(norm):.2f} "
            f"| topP={statistics.mean(tops):.2f} conf={statistics.mean(confs):.2f}"
        )
        rows.append((sname, sbody["truth"], arm, statistics.mean(norm), statistics.pstdev(norm)))

print("\n\n===== SUMMARY (score normalised to 0-10) =====")
truth_rank = {"miss": 0, "pass_minimum": 1, "pass_clean": 2, "exceed": 3}
print(f"{'scenario':<14}{'truth':<14}{'arm':<13}{'mean':>6}{'sd':>6}")
for r in sorted(rows, key=lambda x: (truth_rank[x[1]], x[2])):
    print(f"{r[0]:<14}{r[1]:<14}{r[2]:<13}{r[3]:>6.2f}{r[4]:>6.2f}")

print("\nSpearman-style ordering check (does mean score rise with truth?):")
for arm in ARMS:
    seq = [r[3] for r in sorted(rows, key=lambda x: truth_rank[x[1]]) if r[2] == arm]
    gaps = [round(seq[i + 1] - seq[i], 2) for i in range(len(seq) - 1)]
    print(f"  {arm:<12} means={[round(s,2) for s in seq]} monotonic={all(g > 0 for g in gaps)} gaps={gaps}")
