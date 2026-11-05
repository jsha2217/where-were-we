SKILL=$1/where-were-we; PY="python3 $SKILL/scripts/status.py"
T=$(mktemp -d "$2/t3.XXXX"); pass=0; fail=0
ok(){ if eval "$2"; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1"; fail=$((fail+1)); fi; }
export HOME=$T/home; mkdir -p $HOME; export XDG_CONFIG_HOME=$HOME/.config GIT_CONFIG_GLOBAL=$HOME/.gitconfig
git config --global user.email me@example.com; git config --global user.name me; git config --global init.defaultBranch main
sub(){ python3 -c 'import sys;p,a,b=sys.argv[1:];s=open(p).read();assert a in s,a;open(p,"w").write(s.replace(a,b,1))' "$@"; }
# 1 solo claim/release/done --next
mkdir $T/a && cd $T/a && $PY init >/dev/null
sub STATUS.md "## Next
- " "## Next
- first
- second"
ok "1 claim N in solo moves Next->Now" '$PY claim 1 | grep -q "now: first (from Next)" && grep -A1 "## Now" STATUS.md | grep -q "\[ \] first" && ! sed -n "/## Next/,/## Blocked/p" STATUS.md | grep -q first'
ok "1 claim text adds second Now item" '$PY claim "hotfix" >/dev/null && [ $(sed -n "/## Now/,/## Next/p" STATUS.md | grep -c "\[ \]") = 2 ]'
ok "1 release puts item back on top of Next" '$PY release 2 | grep -q hotfix && sed -n "/## Next/,/## Blocked/p" STATUS.md | sed -n 2p | grep -q hotfix'
$PY done >/dev/null; $PY release >/dev/null 2>&1
sub STATUS.md "## Now
- [ ] second" "## Now
- [ ] "  2>/dev/null
mkdir $T/b && cd $T/b && $PY init >/dev/null
ok "1 done --next works on empty Now" '$PY done --next "start this" | grep -q "now\|Now" ; grep -A1 "## Now" STATUS.md | grep -q "start this"'
mkdir $T/c && cd $T/c && $PY init >/dev/null
ok "1 empty Now hint mentions claim" '$PY done | grep -q "claim"'
ok "1 link block mentions claim" '$PY init --link >/dev/null; grep -q "status.py claim" CLAUDE.md'
# 2 team duplicates
mkdir $T/t && cd $T/t && git init -q && echo x>a && git add a && git commit -qm i && $PY init --team >/dev/null
sub STATUS.md "## Next
- " "## Next
- n1
- n2"
git add -A && git commit -qm t
git checkout -qb p1 && $PY whoami park >/dev/null && $PY claim n2 >/dev/null && git add -A && git commit -qm p1
git checkout -q main && git checkout -qb p2 && $PY whoami kim >/dev/null
out=$($PY claim n2)
ok "2 claim warns when another has it on a branch" 'echo "$out" | grep -q "park already has this in their Now (p1)"'
git add -A && git commit -qm p2 && git checkout -q main && git merge -q --no-edit p1 && git merge -q --no-edit p2 2>/dev/null
ok "2 team flags double claim" '$PY team | grep -q "taken more than once: .n2. by kim, park"'
ok "2 check flags double claim (also --ci)" '$PY check | grep -q "taken more than once" && $PY check --ci | grep -q "taken more than once"'
$PY release >/dev/null
ok "2 after release, no flag" '! $PY check | grep -q "taken more than once"'
# 3 merge conflicts
mkdir $T/m && cd $T/m && git init -q && $PY init --shared >/dev/null
sub STATUS.md "## Goal
- " "## Goal
- Ship v1"
sub STATUS.md "## Next
- " "## Next
- alpha
- beta"
git add -A && git commit -qm base
git checkout -qb x; sub STATUS.md "Ship v1" "Ship v1 by Dec"; sub STATUS.md "- alpha
" ""; git commit -qam x
git checkout -q main; sub STATUS.md "Ship v1" "Ship v1 to 3 pilots"; sub STATUS.md "- beta" "- beta
- gamma"; git commit -qam m
git merge --no-edit x >/dev/null 2>&1; rc=$?
ok "3 same Goal line reworded twice -> git conflict" '[ $rc != 0 ] && git status --short | grep -q "^UU STATUS.md"'
ok "3 markers only around Goal, rest merged" 'grep -q "<<<<<<< ours" STATUS.md && sed -n "/<<<<<<</,/>>>>>>>/p" STATUS.md | grep -q "to 3 pilots" && sed -n "/<<<<<<</,/>>>>>>>/p" STATUS.md | grep -q "by Dec" && ! grep -q alpha STATUS.md && grep -q gamma STATUS.md'
ok "3 exactly one set of markers (no nesting)" '[ $(grep -c "^<<<<<<<" STATUS.md) = 1 ] && [ $(grep -c "^>>>>>>>" STATUS.md) = 1 ]'
ok "3 check reports markers" '$PY check | grep -q "merge conflict markers"'
git merge --abort
git checkout -q -b y main~1 2>/dev/null || git checkout -q -b y HEAD~1
sub STATUS.md "Ship v1" "Ship v1 by Dec"; git commit -qam y; git checkout -q x 2>/dev/null; git checkout -q main
git checkout -qb z main~1; sub STATUS.md "Ship v1" "Ship v1 by Dec"; git commit -qam z
git checkout -q y; git merge --no-edit z >/dev/null 2>&1; rc=$?
ok "3 identical rewording on both sides -> clean" '[ $rc = 0 ] && ! grep -q "<<<<<<<" STATUS.md'
git checkout -q main; git checkout -qb n1 main~1; $PY claim alpha >/dev/null; git commit -qam n1; git checkout -q main~1 -b n2 2>/dev/null; $PY claim beta >/dev/null; git commit -qam n2
git merge --no-edit n1 >/dev/null 2>&1; rc=$?
ok "3 Now: different work on each branch -> both kept, no conflict" '[ $rc = 0 ] && sed -n "/## Now/,/## Next/p" STATUS.md | grep -q alpha && sed -n "/## Now/,/## Next/p" STATUS.md | grep -q beta'
# 4 CRLF
mkdir $T/w && cd $T/w && $PY init >/dev/null
python3 -c 's=open("STATUS.md").read().replace("## Now\n- [ ] \n","## Now\n- [ ] w\n").replace("## Next\n- \n","## Next\n- nx\n");open("STATUS.md","wb").write(s.replace("\n","\r\n").encode())'
$PY done >/dev/null
ok "4 CRLF kept after done" 'python3 -c "d=open(\"STATUS.md\",\"rb\").read(); import sys; sys.exit(not (d.count(b\"\\r\\n\")==d.count(b\"\\n\") and b\"nx\" in d))"'
ok "4 LF file stays LF" 'cd $T/a && ! grep -q $(printf "\r") STATUS.md'
# 5 personal switch
mkdir $T/p && cd $T/p && git init -q && $PY init --shared >/dev/null && printf "# Team\n" > CLAUDE.md && $PY init --link >/dev/null && git add -A && git commit -qm s
out=$($PY init --personal)
ok "5 switch to personal mentions link block" 'echo "$out" | grep -q "init --link. moves the block"'
out=$($PY init --link)
ok "5 init --link moves block out of shared files" 'echo "$out" | grep -q "moved the Project status block out of CLAUDE.md" && ! grep -q where-were-we CLAUDE.md && grep -q "# Team" CLAUDE.md && grep -q where-were-we CLAUDE.local.md'
ok "5 AGENTS.md that only held the block is removed" '[ ! -e AGENTS.md ]'
# link block refreshed in place on mode switch
mkdir $T/lk && cd $T/lk && git init -q && printf "# Mine\n\nintro\n" > CLAUDE.md && $PY init --shared >/dev/null && $PY init --link >/dev/null && printf "\n## After\nkeep me last\n" >> CLAUDE.md
out=$($PY init --team)
ok "link block refreshed for team mode" 'echo "$out" | grep -q "updated the Project status block in CLAUDE.md" && grep -q "Team project" CLAUDE.md'
ok "refresh keeps the user's layout" 'tail -1 CLAUDE.md | grep -q "keep me last" && head -1 CLAUDE.md | grep -q "# Mine"'
ok "no change, no message" '! $PY init | grep -q "updated the Project status block"'
# commands from a subfolder
mkdir -p $T/sub/apps/api/src && cd $T/sub && git init -q && $PY init >/dev/null
cd apps/api/src
ok "subfolder: claim finds the project" '$PY claim "from sub" | grep -q "(project: ../../..)" && grep -q "from sub" $T/sub/STATUS.md'
ok "subfolder: offer says exists" '$PY offer | grep -q "^exists"'
ok "subfolder: init refused, nothing created" '! $PY init >/dev/null && [ ! -e .where-were-we ]'
ok "subfolder: init --force makes a separate one" '$PY init --force >/dev/null && [ -f .where-were-we/config.json ]'
mkdir -p $T/outside/deep && cd $T/outside/deep
ok "outside any project: not set up" '$PY claim x | grep -q "not set up"'
# empty Now between tasks
mkdir $T/en && cd $T/en && $PY init >/dev/null
ok "both Now and Next empty -> warn" '$PY check | grep -q "both empty"'
sub STATUS.md "## Next
- " "## Next
- later"
ok "Now empty but Next has items -> no warning" '! $PY check | grep -q "Now"'
mkdir -p $T/hub/proj && cd $T/hub/proj && $PY init >/dev/null && cd $T/hub
ok "offer elsewhere tells to start inside next time" '$PY offer | grep -q "start the agent inside proj next time"'
# older decisions pointer
mkdir $T/od && cd $T/od && $PY init >/dev/null && for i in 1 2 3 4 5; do $PY decide --accepted "dec $i" >/dev/null; done
ok "older line shows hidden count" 'grep -qx -- "- (+2 older: .where-were-we/decisions.md)" STATUS.md'
ok "older line not captured as a decision" '$PY sync | grep -vq captured && [ $(grep -c "^- D-" .where-were-we/decisions.md) = 5 ]'
ok "check not out of sync with older line" '! $PY check | grep -q "out of sync\|missing from"'
$PY pin D-1 >/dev/null
ok "pinned counts as shown" 'grep -qx -- "- (+1 older: .where-were-we/decisions.md)" STATUS.md'
mkdir $T/odk && cd $T/odk && $PY init --ko >/dev/null && for i in 1 2 3 4; do $PY decide "결정 $i" >/dev/null; done
ok "ko older line" 'grep -qx -- "- (이전 결정 1개: .where-were-we/decisions.md)" STATUS.md && ! $PY check | grep -q "out of sync"'
# newer copy warning
mkdir $T/nw && cd $T/nw && git init -q && $PY init --shared >/dev/null && sed -i '' 's/^VERSION = ".*"/VERSION = "9.9.9"/' .where-were-we/status.py
ok "newer copy warning names tampering" '$PY check | grep -q "raised version number is also how a tampered copy"'
ok "init keeps newer copy but says check git log" '$PY init | grep -q "check .git log -p"'
# fetch never waits for credentials
git remote add origin ssh://git@nonexistent.invalid/x.git
s=$(date +%s); $PY team --fetch >/dev/null 2>&1; e=$(( $(date +%s) - s ))
ok "team --fetch with unreachable ssh remote returns fast ($e s)" '[ $e -lt 30 ]'
# 6 staleness wording
mkdir $T/s && cd $T/s && git init -q && $PY init --shared >/dev/null && git add -A && git commit -qm s && for i in 1 2 3 4 5; do echo $i>>c; git add c; git commit -qm c$i; done
ok "6 staleness wording" '$PY check | grep -q "warn:  5 commits since STATUS.md"'
echo "== $pass passed, $fail failed"; rm -rf "$T"; [ $fail = 0 ]
