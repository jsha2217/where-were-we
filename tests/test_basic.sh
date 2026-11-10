#!/bin/bash
# Everything the helper does: init, claim, done, decide, check, staying out of git, parallel writers.
SKILL=$1/where-were-we; PY="python3 $SKILL/scripts/status.py"
T=$(mktemp -d "$2/tb.XXXX"); pass=0; fail=0
ok(){ if eval "$2"; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1"; fail=$((fail+1)); fi; }
sub(){ python3 -c 'import sys;p,a,b=sys.argv[1:];s=open(p).read();assert a in s,a;open(p,"w").write(s.replace(a,b,1))' "$@"; }
export HOME=$T/home; mkdir -p $HOME; export GIT_CONFIG_GLOBAL=$HOME/.gitconfig
git config --global user.email me@example.com; git config --global user.name me; git config --global init.defaultBranch main

# 1 init: out of git, link block
mkdir $T/p && cd $T/p && git init -q && echo a > a && git add a && git commit -qm a
printf '# My notes\n' > CLAUDE.local.md
$PY init --local --link >/dev/null
ok "1 files created" '[ -f STATUS.md ] && [ -f .where-were-we/decisions.md ] && [ -d .where-were-we/log ]'
ok "1 nothing shows in git status" '[ -z "$(git status --porcelain)" ]'
ok "1 link block appended, user text kept" 'head -1 CLAUDE.local.md | grep -q "My notes" && grep -q "where-were-we:start" CLAUDE.local.md'
ok "1 init again changes nothing" '$PY init --link | grep -q "already" && [ $(grep -c "where-were-we:start" CLAUDE.local.md) = 1 ] && [ $(grep -c "^# where-were-we" .git/info/exclude) = 1 ]'
ok "1 commands before init refuse" 'mkdir $T/q && cd $T/q && ! $PY claim x >/dev/null && [ ! -e STATUS.md ]'

# 2 claim / done
cd $T/p
sub STATUS.md "## Next
- " "## Next
- first task
- second task"
ok "2 claim N moves Next to Now" '$PY claim 1 | grep -q "now: first task (from Next)" && grep -A1 "## Now" STATUS.md | grep -q "\[ \] first task" && ! sed -n "/## Next/,/## Blocked/p" STATUS.md | grep -q first'
ok "2 claim by text" '$PY claim second | grep -q "(from Next)" && sed -n "/## Next/,/## Blocked/p" STATUS.md | grep -qx -- "- "'
ok "2 claim new text adds it" '$PY claim "hotfix login" >/dev/null && [ $(sed -n "/## Now/,/## Next/p" STATUS.md | grep -c "\[ \]") = 3 ]'
ok "2 claim bad number refuses" '! $PY claim 7 >/dev/null'
ok "2 done with several items asks which" '! $PY done >/dev/null'
ok "2 done by text logs it" '$PY done hotfix | grep -q "done: hotfix login" && grep -q "hotfix login" .where-were-we/log/*.md && ! grep -q hotfix STATUS.md'
ok "2 done by number" '$PY done 1 >/dev/null && ! grep -q "first task" STATUS.md'
ok "2 done with one item needs no argument" '$PY done >/dev/null && grep -A1 "## Now" STATUS.md | grep -qx -- "- \[ \] "'
ok "2 done with empty Now refuses" '! $PY done >/dev/null'
ok "2 log groups by date" '[ $(grep -c "^## " .where-were-we/log/*.md) = 1 ] && [ $(grep -c "^- " .where-were-we/log/*.md) = 3 ]'

# 3 decide
for i in 1 2 3 4 5 6 7; do $PY decide "choice $i" >/dev/null; done
ok "3 numbered in decisions.md with dates" 'grep -q "^- D-007 (....-..-..): choice 7" .where-were-we/decisions.md'
ok "3 STATUS.md shows the last 5 and an older line" 'grep -qx -- "- D-007: choice 7" STATUS.md && ! grep -q "choice 2$" STATUS.md && grep -qx -- "- (+2 older: .where-were-we/decisions.md)" STATUS.md'

# 4 check
ok "4 clean file passes" '$PY check | grep -q "^ok"'
python3 -c 'p="STATUS.md";s=open(p).read();open(p,"w").write(s+"".join("\n- x" for _ in range(40)))'
ok "4 over 50 lines fails" '! $PY check >/dev/null'
sub STATUS.md "## Blocked" "## Stuck"
ok "4 missing section fails, names it" '$PY check | grep -q "missing section .## Blocked"'
ok "4 claim refuses without the section it needs" 'sub STATUS.md "## Next" "## Later" && ! $PY claim y >/dev/null 2>&1'

# 5 subfolder, branches
mkdir $T/r && cd $T/r && git init -q && echo a > a && git add a && git commit -qm a && $PY init --local >/dev/null && mkdir -p src/deep
ok "5 works from a subfolder" 'cd src/deep && $PY claim "from sub" >/dev/null && grep -q "from sub" $T/r/STATUS.md'
cd $T/r && git checkout -qb feat && echo b > b && git add b && git commit -qm b && git checkout -q main && git merge -q --no-edit feat
ok "5 branch switch and merge leave it alone" 'grep -q "from sub" STATUS.md && git add -A && [ -z "$(git diff --cached --name-only)" ]'

# 6 parallel writers: two windows and subagents at once
mkdir $T/c && cd $T/c && $PY init --local >/dev/null
for i in $(seq 20); do $PY claim "task $i" >/dev/null & done; wait
ok "6 20 parallel claims all kept" '[ $(grep -c "^- \[ \] task" STATUS.md) = 20 ]'
for i in $(seq 10); do $PY decide "parallel $i" >/dev/null & done; wait
ok "6 10 parallel decisions, unique numbers" '[ $(grep -c "^- D-" .where-were-we/decisions.md) = 10 ] && [ $(grep -o "^- D-[0-9]*" .where-were-we/decisions.md | sort -u | wc -l) -eq 10 ]'
ok "6 no lock or temp files left" '[ -z "$(ls -A .where-were-we | grep -v "decisions.md\|log")" ] && [ -z "$(ls -A | grep "\.tmp")" ]'
touch .where-were-we/.lock; touch -t 202001010000 .where-were-we/.lock
ok "6 a stale lock from a crash is cleared" '$PY claim "after crash" >/dev/null && grep -q "after crash" STATUS.md'

echo "== $pass passed, $fail failed"; rm -rf "$T"; [ $fail = 0 ]
