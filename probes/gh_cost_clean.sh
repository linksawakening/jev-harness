#!/usr/bin/env bash
# Clean re-measurement: isolate each operation, one at a time, no inline gh calls
# inside a measurement window. Reports GraphQL points per operation.
set -uo pipefail

OWNER="@me"
REMAIN() { gh api graphql -f query='query { rateLimit { remaining resetAt } }' --jq '.data.rateLimit.remaining'; }

NUM=$(gh project create --owner "$OWNER" --title "jev-cost-probe" --format json | python3 -c 'import sys,json;print(json.load(sys.stdin)["number"])')
PID=$(gh project view "$NUM" --owner "$OWNER" --format json | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

# --- pre-create everything OUTSIDE any measurement window ---
gh project field-create "$NUM" --owner "$OWNER" --name "JevBand" --data-type SINGLE_SELECT \
  --single-select-options "rework,complete,harvest" >/dev/null
gh project field-create "$NUM" --owner "$OWNER" --name "JevScore" --data-type NUMBER >/dev/null

FIELDS=$(gh project field-list "$NUM" --owner "$OWNER" --format json)
FBAND=$(echo "$FIELDS" | python3 -c 'import sys,json;print(next(f["id"] for f in json.load(sys.stdin)["fields"] if f["name"]=="JevBand"))')
FSCORE=$(echo "$FIELDS" | python3 -c 'import sys,json;print(next(f["id"] for f in json.load(sys.stdin)["fields"] if f["name"]=="JevScore"))')
OPTBAND=$(echo "$FIELDS" | python3 -c 'import sys,json;print(next(f["options"][1]["id"] for f in json.load(sys.stdin)["fields"] if f["name"]=="JevBand"))')

# 20 draft items, created outside measurement
IDS=$(for i in $(seq 1 20); do
  gh project item-create "$NUM" --owner "$OWNER" --title "task $i" --format json \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])'
done)
IID=$(echo "$IDS" | head -1)

measure() { # name, then command
  local name="$1"; shift
  local a b
  a=$(REMAIN)
  "$@" >/dev/null 2>&1
  b=$(REMAIN)
  printf '%-38s %3d point(s)\n' "$name" "$((a - b))"
  echo "   (engine: gh='$*' )"
}

echo "===== PER-OPERATION GRAPHQL COST ====="
measure "number field write (score)" gh project item-edit --id "$IID" --project-id "$PID" --field-id "$FSCORE" --number 7
measure "single-select write (band)" gh project item-edit --id "$IID" --project-id "$PID" --field-id "$FBAND" --single-select-option-id "$OPTBAND"
measure "number field write (repeat, warm)" gh project item-edit --id "$IID" --project-id "$PID" --field-id "$FSCORE" --number 8
measure "board read: 20 items w/ fields" gh project item-list "$NUM" --owner "$OWNER" --format json --limit 100
measure "board read: 5 items w/ fields" gh project item-list "$NUM" --owner "$OWNER" --format json --limit 5
measure "issue create (task from issue)" gh issue create --title "probe issue" --body "x" --repo linksawakening/hermes-cost-probe

# --- project-scoped writes, for the payload-size ceiling question ---
measure "project field-list read" gh project field-list "$NUM" --owner "$OWNER" --format json

echo
echo "===== BATCH (simulating a full board tick) ====="
B0=$(REMAIN)
# 20 items x (score + band) = 40 field writes + 1 board read
for id in $IDS; do
  gh project item-edit --id "$id" --project-id "$PID" --field-id "$FSCORE" --number 5 >/dev/null 2>&1
  gh project item-edit --id "$id" --project-id "$PID" --field-id "$FBAND" --single-select-option-id "$OPTBAND" >/dev/null 2>&1
done
gh project item-list "$NUM" --owner "$OWNER" --format json --limit 100 >/dev/null 2>&1
B1=$(REMAIN)
echo "full tick: 20 tasks x 2 writes + 1 read = $((B0 - B1)) points"
echo "  -> per-transition amortised: $(python3 -c "print(round($((B0-B1))/41, 2))") points"

echo
echo "===== CLEANUP ====="
gh project delete "$NUM" --owner "$OWNER" >/dev/null 2>&1 && echo "project deleted"
echo "remaining: $(REMAIN)"
