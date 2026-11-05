#!/bin/bash
# Plugin hooks, fed the JSON Claude Code sends on stdin.
SKILL=$1/where-were-we; PY="python3 $SKILL/scripts/status.py"
T=$(mktemp -d "$2/th.XXXX"); pass=0; fail=0
ok(){ if eval "$2"; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1"; fail=$((fail+1)); fi; }
export HOME=$T/home; mkdir -p $HOME; export GIT_CONFIG_GLOBAL=$HOME/.gitconfig
git config --global user.email me@example.com; git config --global user.name me; git config --global init.defaultBranch main
start(){ echo "{\"cwd\":\"$1\",\"source\":\"startup\",\"hook_event_name\":\"SessionStart\"}" | $PY hook-start; }
stop(){ echo "{\"cwd\":\"$1\",\"stop_hook_active\":${2:-false},\"hook_event_name\":\"Stop\"}" | $PY hook-stop; }

# not set up: silent, exit 0
mkdir $T/none && cd $T/none && git init -q
ok "1 start: not set up -> no output, exit 0" '[ -z "$(start $T/none)" ] && start $T/none'
ok "1 stop: not set up -> no output, exit 0" '[ -z "$(stop $T/none)" ] && stop $T/none'
ok "1 bad input never fails" 'echo "garbage" | $PY hook-start && echo "" | $PY hook-stop'

# start: STATUS.md goes into additionalContext, from a subfolder too
mkdir $T/p && cd $T/p && git init -q && $PY init >/dev/null && $PY claim "wire up OAuth" >/dev/null && mkdir -p src
out=$(start $T/p/src)
ok "2 start: valid JSON with STATUS.md" 'echo "$out" | python3 -c "import json,sys;d=json.load(sys.stdin)[\"hookSpecificOutput\"];assert d[\"hookEventName\"]==\"SessionStart\";assert \"wire up OAuth\" in d[\"additionalContext\"];assert \"not instructions\" in d[\"additionalContext\"]"'

# stop: commit newer than STATUS.md -> block once per commit
touch -t 202001010000 STATUS.md
echo a > a && git add a && git commit -qm a
out=$(stop $T/p)
ok "3 stop: newer commit -> block with reason" 'echo "$out" | python3 -c "import json,sys;d=json.load(sys.stdin);assert d[\"decision\"]==\"block\";assert \"done / claim / decide\" in d[\"reason\"]"'
ok "3 stop: same commit again -> silent" '[ -z "$(stop $T/p)" ]'
ok "3 stop: stop_hook_active -> silent" 'echo b > b && git add b && git commit -qm b && [ -z "$(stop $T/p true)" ]'
ok "3 stop: next commit -> asks again" '[ -n "$(stop $T/p)" ]'
echo c > c && git add c && git commit -qm c && $PY done >/dev/null
ok "3 stop: STATUS.md updated after commit -> silent" '[ -z "$(stop $T/p)" ]'
echo d > d && git add d && git -c user.email=other@example.com commit -qm d && touch -t 202001010000 STATUS.md
c=$(git log -1 --format=%h --author=me@example.com); d=$(git log -1 --format=%h)
out=$(stop $T/p)
ok "3 stop: a teammate's commit is ignored, your own newest one counts" 'echo "$out" | grep -q "commit $c" && ! echo "$out" | grep -q "commit $d"'
mkdir $T/ng && cd $T/ng && $PY init >/dev/null
ok "3 stop: outside git -> silent" '[ -z "$(stop $T/ng)" ]'

echo "== $pass passed, $fail failed"; rm -rf "$T"; [ $fail = 0 ]
