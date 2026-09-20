#!/usr/bin/env python3
"""Find the Score ladder cap: how many rungs does the API accept, and what's the error."""
from __future__ import annotations

import json
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
STATE = {"task": "placeholder", "observations": ["nothing"]}


def call(criteria, label):
    q = {"success": {"type": "score", "instructions": "Rate success.", "criteria": criteria}}
    body = json.dumps({"state": STATE, "model": "jev-1.13.0", "questions": q}).encode()
    req = urllib.request.Request(
        URL, data=body,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            a = json.loads(resp.read())["answers"]["success"]
            print(f"{label:>4} rungs: OK score={a['score']:.2f} legend_size={len(a['legend'])}")
            return True
    except urllib.error.HTTPError as e:
        print(f"{label:>4} rungs: HTTP {e.code} {e.read().decode()[:400]}")
        return False


for n in (3, 4, 5, 6, 7, 8, 9, 11):
    if not call([f"level {i}" for i in range(n)], n):
        break
