#!/bin/bash
# Core commands: init, claim/done/release, decisions, offer, check.
SKILL=$1/where-were-we
PY="python3 $SKILL/scripts/status.py"
T=$(mktemp -d "$2/t.XXXX")
pass=0; fail=0
ok(){ if eval "$2"; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1"; fail=$((fail+1)); fi; }
mode(){ stat -f %Lp "$1"; }
sub(){ python3 -c 'import sys;p,a,b=sys.argv[1:];s=open(p).read();assert a in s,a;open(p,"w").write(s.replace(a,b,1))' "$@"; }
export HOME=$T/home; mkdir -p $HOME; export XDG_CONFIG_HOME=$HOME/.config
export GIT_CONFIG_GLOBAL=$HOME/.gitconfig; git config --global user.email t@example.com; git config --global user.name t
git config --global init.defaultBranch main
umask 022

# --- 1. permissions, symlinked CLAUDE.local.md
P=$T/p1; mkdir -p $P && cd $P && git init -q
printf '# Mine\n' > notes.md; chmod 644 notes.md; ln -s notes.md CLAUDE.local.md
$PY init --link >/dev/null
ok "1 new STATUS.md follows umask (644)" '[ "$(mode STATUS.md)" = 644 ]'
ok "1 CLAUDE.local.md is still a symlink" '[ -L CLAUDE.local.md ]'
ok "1 link block written through the symlink, file keeps 644" 'grep -q "where-were-we:start" notes.md && [ "$(mode notes.md)" = 644 ]'
ok "1 .git/info/exclude not 600" '[ "$(mode .git/info/exclude)" != 600 ]'
ok "1 no helper copy, no .gitattributes" '[ ! -e .where-were-we/status.py ] && [ ! -e .gitattributes ]'
ok "1 nothing shows in git status" '[ "$(git status --porcelain)" = "?? notes.md" ]'
ok "1 CLAUDE.md and AGENTS.md not created" '[ ! -e CLAUDE.md ] && [ ! -e AGENTS.md ]'

# --- 2. claim / release / done
mkdir $T/a && cd $T/a && $PY init >/dev/null
sub STATUS.md "## Next
- " "## Next
- first
- second"
ok "2 claim N moves Next->Now" '$PY claim 1 | grep -q "now: first (from Next)" && grep -A1 "## Now" STATUS.md | grep -q "\[ \] first" && ! sed -n "/## Next/,/## Blocked/p" STATUS.md | grep -q first'
ok "2 claim text adds a second Now item" '$PY claim "hotfix" >/dev/null && [ $(sed -n "/## Now/,/## Next/p" STATUS.md | grep -c "\[ \]") = 2 ]'
ok "2 done with two Now items asks which" '! $PY done >/dev/null'
ok "2 release puts item back on top of Next" '$PY release 2 | grep -q hotfix && sed -n "/## Next/,/## Blocked/p" STATUS.md | sed -n 2p | grep -q hotfix'
ok "2 done by text logs it and promotes Next" '$PY done first | grep -q "now: hotfix (from Next)" && grep -q "first" .where-were-we/log/*.md'
ok "2 done --next starts a new item" '$PY done --next "brand new" >/dev/null && grep -A1 "## Now" STATUS.md | grep -q "brand new"'
ok "2 done --no-promote leaves Now empty, no nagging while Next has items" 'out=$($PY done --no-promote) && ! echo "$out" | grep -q "empty" && grep -A1 "## Now" STATUS.md | grep -qx -- "- \[ \] "'
ok "2 ticked item is archived" 'sub STATUS.md "## Now
- [ ] " "## Now
- [x] ticked one" && $PY archive | grep -q "archived 1" && grep -q "ticked one" .where-were-we/log/*.md'

# --- 3. existing notes, foreign STATUS.md
P=$T/p3a; mkdir -p $P && cd $P && printf 'notes\n' > TODO.md
ok "3 hint points to references/adopting.md" '$PY init | grep -q "references/adopting.md"'
P=$T/p3b; mkdir -p $P && cd $P && printf '# my own notes\n' > STATUS.md
out=$($PY offer); rc=$?
ok "3 foreign STATUS.md is offered (exit 0)" '[ $rc = 0 ] && echo "$out" | grep -q "not made by where-were-we"'
ok "3 init refuses the foreign file" '! $PY init >/dev/null'
mkdir -p .where-were-we/log && mv STATUS.md .where-were-we/log/legacy.md && $PY init >/dev/null
ok "3 set-up folder says exists" '! $PY offer | grep -q "^offer" '

# --- 4. offer in home: no subfolder scan
mkdir -p $HOME/Desktop/proj/.where-were-we && echo '{}' > $HOME/Desktop/proj/.where-were-we/config.json
cd $HOME && out=$($PY offer)
ok "4 home says not a project folder (no scan)" 'echo "$out" | grep -q "not a project folder"'
cd $HOME/Desktop && out=$($PY offer)
ok "4 inside Desktop, its subfolders are searched" 'echo "$out" | grep -q "elsewhere: proj"'
mkdir -p $T/work/app/.where-were-we && echo '{}' > $T/work/app/.where-were-we/config.json
cd $T/work && ok "4 normal folder still finds subprojects" '$PY offer | grep -q "elsewhere: app"'
mkdir -p $T/hub/proj && cd $T/hub/proj && $PY init >/dev/null && cd $T/hub
ok "4 offer elsewhere tells to start inside next time" '$PY offer | grep -q "start the agent inside proj next time"'

# --- 5. hand-reworded decisions survive
P=$T/p5; mkdir -p $P && cd $P && $PY init >/dev/null
$PY decide "Use Postgres, not SQLite — several writers" >/dev/null
$PY decide --accepted "Use FastAPI, not Flask — async" >/dev/null
sed -i '' 's/Use Postgres, not SQLite — several writers/Use Postgres 16, not SQLite — many writers/' STATUS.md
out=$($PY sync)
ok "5 sync reports the rewording" 'echo "$out" | grep -q "hand-edited wording of D-001"'
ok "5 wording kept in STATUS.md" 'grep -q "Postgres 16" STATUS.md'
ok "5 wording copied to decisions.md" 'grep -q "D-001 (.*) \[proposed\]: Use Postgres 16" .where-were-we/decisions.md'
ok "5 no duplicate decision created" '[ $(grep -c "^- D-" .where-were-we/decisions.md) = 2 ]'
sed -i '' 's/D-001 \[proposed\]/D-001/' STATUS.md
out=$($PY sync)
ok "5 hand-removed [proposed] is reported, not applied" 'echo "$out" | grep -q "tags edited by hand" && grep -q "D-001 \[proposed\]" STATUS.md'
$PY decide "Cache with Redis" >/dev/null
ok "5 decide still works" 'grep -q "D-003 \[proposed\]: Cache with Redis" STATUS.md'
ok "5 pin refuses a proposed decision" '! $PY pin D-3 >/dev/null'
P=$T/p5b; mkdir -p $P && cd $P && $PY init >/dev/null
$PY decide "Alpha" >/dev/null
printf -- '- D-001 (2026-11-05) [proposed]: Beta\n' >> .where-were-we/decisions.md
out=$($PY sync)
ok "5 duplicate renumbered, texts unchanged" 'echo "$out" | grep -q "renumbered" && grep -q ": Alpha" .where-were-we/decisions.md && grep -q ": Beta" .where-were-we/decisions.md && ! echo "$out" | grep -q "hand-edited"'

# --- 6. older decisions pointer
mkdir $T/od && cd $T/od && $PY init >/dev/null && for i in 1 2 3 4 5; do $PY decide --accepted "dec $i" >/dev/null; done
ok "6 older line shows hidden count" 'grep -qx -- "- (+2 older: .where-were-we/decisions.md)" STATUS.md'
ok "6 older line not captured as a decision" '$PY sync | grep -vq captured && [ $(grep -c "^- D-" .where-were-we/decisions.md) = 5 ]'
ok "6 check not out of sync with older line" '! $PY check | grep -q "out of sync\|missing from"'
$PY pin D-1 >/dev/null
ok "6 pinned counts as shown" 'grep -qx -- "- (+1 older: .where-were-we/decisions.md)" STATUS.md'
mkdir $T/odk && cd $T/odk && $PY init --ko >/dev/null && for i in 1 2 3 4; do $PY decide "결정 $i" >/dev/null; done
ok "6 ko older line" 'grep -qx -- "- (이전 결정 1개: .where-were-we/decisions.md)" STATUS.md && ! $PY check | grep -q "out of sync"'

# --- 7. check
mkdir $T/en && cd $T/en && $PY init >/dev/null
ok "7 both Now and Next empty -> warn" '$PY check | grep -q "both empty"'
sub STATUS.md "## Next
- " "## Next
- later"
ok "7 Now empty but Next has items -> no warning" '! $PY check | grep -q "Now"'
sub STATUS.md "## Blocked
- (none)" "## Blocked
- waiting on keys"
ok "7 ownerless Blocked line warns" '$PY check | grep -q "without an owner"'
python3 -c 'p="STATUS.md";s=open(p).read();open(p,"w").write(s+"".join("\n- x" for _ in range(40)))'
ok "7 over 50 lines is an error" '! $PY check >/dev/null'

# --- 8. CRLF
mkdir $T/w && cd $T/w && $PY init >/dev/null
python3 -c 's=open("STATUS.md").read().replace("## Now\n- [ ] \n","## Now\n- [ ] w\n").replace("## Next\n- \n","## Next\n- nx\n");open("STATUS.md","wb").write(s.replace("\n","\r\n").encode())'
$PY done >/dev/null
ok "8 CRLF kept after done" 'python3 -c "d=open(\"STATUS.md\",\"rb\").read(); import sys; sys.exit(not (d.count(b\"\\r\\n\")==d.count(b\"\\n\") and b\"nx\" in d))"'
ok "8 LF file stays LF" 'cd $T/a && ! grep -q $(printf "\r") STATUS.md'

# --- 9. commands from a subfolder
mkdir -p $T/sub/apps/api/src && cd $T/sub && git init -q && $PY init >/dev/null
cd apps/api/src
ok "9 claim finds the project" '$PY claim "from sub" | grep -q "(project: ../../..)" && grep -q "from sub" $T/sub/STATUS.md'
ok "9 offer says exists" '$PY offer | grep -q "^exists"'
ok "9 init refused, nothing created" '! $PY init >/dev/null && [ ! -e .where-were-we ]'
ok "9 init --force makes a separate one" '$PY init --force >/dev/null && [ -f .where-were-we/config.json ]'
mkdir -p $T/outside/deep && cd $T/outside/deep
ok "9 outside any project: not set up" '$PY claim x | grep -q "not set up"'

echo "== $pass passed, $fail failed"
rm -rf "$T"
[ $fail = 0 ]
