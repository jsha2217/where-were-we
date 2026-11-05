#!/bin/bash
# Regression tests for where-were-we v0.9.4 fixes
SKILL=$1/where-were-we
PY="python3 $SKILL/scripts/status.py"
T=$(mktemp -d "$2/t.XXXX")
pass=0; fail=0
ok(){ if eval "$2"; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1"; fail=$((fail+1)); fi; }
mode(){ stat -f %Lp "$1"; }
export HOME=$T/home; mkdir -p $HOME; export XDG_CONFIG_HOME=$HOME/.config
export GIT_CONFIG_GLOBAL=$HOME/.gitconfig; git config --global user.email t@example.com; git config --global user.name t
umask 022

# --- 1. permissions + symlink
P=$T/p1; mkdir -p $P && cd $P && git init -q
printf '# Agents\n' > AGENTS.md; chmod 644 AGENTS.md; ln -s AGENTS.md CLAUDE.md
printf '* text=auto\n' > .gitattributes; chmod 664 .gitattributes
$PY init --shared >/dev/null; $PY init --link >/dev/null
ok "1 AGENTS.md keeps 644" '[ "$(mode AGENTS.md)" = 644 ]'
ok "1 .gitattributes keeps 664" '[ "$(mode .gitattributes)" = 664 ]'
ok "1 new STATUS.md follows umask (644)" '[ "$(mode STATUS.md)" = 644 ]'
ok "1 CLAUDE.md is still a symlink" '[ -L CLAUDE.md ]'
ok "1 AGENTS.md got the link block" 'grep -q "where-were-we:start" AGENTS.md'
ok "1 .git/info/exclude untouched or not 600" '[ ! -e .git/info/exclude ] || [ "$(mode .git/info/exclude)" != 600 ]'

# --- 2. sensitive scan
ed(){ python3 - "$1" "$2" <<'PY'
import sys,re
p,item=sys.argv[1:]
s=open(p).read()
s=re.sub(r"(## Next\n)", r"\1- "+item.replace("\\","\\\\")+"\n", s,1)
open(p,"w").write(s)
PY
}
P=$T/p2; mkdir -p $P && cd $P && git init -q && $PY init --shared >/dev/null
ed STATUS.md 'Switch remote to git@github.com:org/repo.git'
ed STATUS.md 'Clone ssh://git@github.com/org/repo for CI'
ok "2 git remotes are not emails" '$PY check --ci >/dev/null'
ed STATUS.md 'Type `token: string` in api.ts'
ed STATUS.md 'Run with pwd: /usr/src'
out=$($PY check --ci); rc=$?
ok "2 token/pwd only warn, exit 0" '[ $rc = 0 ] && echo "$out" | grep -q "warn:  looks like a password"'
ed STATUS.md 'Mail john.doe@gmail.com about it'
out=$($PY check --ci); rc=$?
ok "2 real email still an error" '[ $rc = 1 ] && echo "$out" | grep -q "email address"'
ln=$(grep -n "john.doe" STATUS.md | cut -d: -f1)
out=$($PY allow STATUS.md:$ln)
ok "3 allow accepted" 'echo "$out" | grep -q "allowed on the user"'
ok "3 config holds no raw value" '! grep -q john .where-were-we/config.json && grep -q "\"kind\": \"email address\"" .where-were-we/config.json'
ok "3 check passes after allow" '$PY check --ci >/dev/null'
ed STATUS.md 'Also bob@corp.io'
ok "3 a different email still fails" '! $PY check --ci >/dev/null'
ok "3 allow on a clean line refuses" '! $PY allow STATUS.md:1 >/dev/null'
ok "3 allow bad spec refuses" '! $PY allow README.md:1 >/dev/null'
$PY allow --reset >/dev/null
ln=$(grep -n "bob@" STATUS.md | cut -d: -f1); sed -i '' "${ln}d" STATUS.md
ok "3 reset brings the error back" '! $PY check --ci >/dev/null'
ed STATUS.md 'key ghp_abcdefghijklmnopqrstuvwx'
ok "2 GitHub token is still an error" '$PY check --ci | grep -q "API key"'

# --- 4a hint
P=$T/p4a; mkdir -p $P && cd $P && printf 'notes\n' > TODO.md
ok "4a hint points to references/adopting.md" '$PY init | grep -q "references/adopting.md"'

# --- 4b offer with a foreign STATUS.md
P=$T/p4b; mkdir -p $P && cd $P && printf '# my own notes\n' > STATUS.md
out=$($PY offer); rc=$?
ok "4b foreign STATUS.md is offered (exit 0)" '[ $rc = 0 ] && echo "$out" | grep -q "not made by where-were-we"'
ok "4b init refuses the foreign file" '! $PY init >/dev/null'
mkdir -p .where-were-we/log && mv STATUS.md .where-were-we/log/legacy.md && $PY init >/dev/null
ok "4b set-up folder says exists" '! $PY offer | grep -q "^offer" '

# --- 4c helper version handling
P=$T/p4c; mkdir -p $P && cd $P && $PY init >/dev/null
sed -i '' 's/^VERSION = ".*"/VERSION = "9.9.9"/' .where-were-we/status.py
out=$($PY init)
ok "4c newer project copy is kept" 'echo "$out" | grep -q "kept .where-were-we/status.py v9.9.9" && grep -q "9.9.9" .where-were-we/status.py'
sed -i '' 's/^VERSION = ".*"/VERSION = "0.9.1"/' .where-were-we/status.py
ok "4c older copy is updated" '$PY init | grep -q "v0.9.1 -> v" && cmp -s .where-were-we/status.py $SKILL/scripts/status.py'
echo "# tampered" >> .where-were-we/status.py
ok "4c same version, changed content is replaced" '$PY init | grep -q "replaced .where-were-we/status.py" && cmp -s .where-were-we/status.py $SKILL/scripts/status.py'
ok "4c identical copy is left alone" '! $PY init | grep -q "status.py (v\|replaced\|updated helper"'

# --- 4d offer in home: no subfolder scan
mkdir -p $HOME/Desktop/proj/.where-were-we && echo '{}' > $HOME/Desktop/proj/.where-were-we/config.json
cd $HOME && out=$($PY offer)
ok "4d home says not a project folder (no scan)" 'echo "$out" | grep -q "not a project folder"'
cd $HOME/Desktop && out=$($PY offer)
ok "4d inside Desktop, its subfolders are searched" 'echo "$out" | grep -q "elsewhere: proj"'
mkdir -p $T/work/app/.where-were-we && echo '{}' > $T/work/app/.where-were-we/config.json
cd $T/work && ok "4d normal folder still finds subprojects" '$PY offer | grep -q "elsewhere: app"'

# --- 4e hand-reworded decisions survive
P=$T/p4e; mkdir -p $P && cd $P && $PY init >/dev/null
$PY decide "Use Postgres, not SQLite — several writers" >/dev/null
$PY decide --accepted "Use FastAPI, not Flask — async" >/dev/null
sed -i '' 's/Use Postgres, not SQLite — several writers/Use Postgres 16, not SQLite — many writers/' STATUS.md
out=$($PY sync)
ok "4e sync reports the rewording" 'echo "$out" | grep -q "hand-edited wording of D-001"'
ok "4e wording kept in STATUS.md" 'grep -q "Postgres 16" STATUS.md'
ok "4e wording copied to decisions.md" 'grep -q "D-001 (.*) \[proposed\]: Use Postgres 16" .where-were-we/decisions.md'
ok "4e no duplicate decision created" '[ $(grep -c "^- D-" .where-were-we/decisions.md) = 2 ]'
sed -i '' 's/D-001 \[proposed\]/D-001/' STATUS.md
out=$($PY sync)
ok "4e hand-removed [proposed] is reported, not applied" 'echo "$out" | grep -q "tags edited by hand" && grep -q "D-001 \[proposed\]" STATUS.md'
ok "4e check clean after sync (except proposed notice)" '$PY check --ci >/dev/null'
$PY decide "Cache with Redis" >/dev/null
ok "4e decide still works" 'grep -q "D-003 \[proposed\]: Cache with Redis" STATUS.md'

# --- 4e after a union-merge duplicate, no bogus rewording
P=$T/p4e2; mkdir -p $P && cd $P && $PY init >/dev/null
$PY decide "Alpha" >/dev/null
printf -- '- D-001 (2026-11-05) [proposed]: Beta\n' >> .where-were-we/decisions.md
out=$($PY sync)
ok "4e duplicate renumbered, texts unchanged" 'echo "$out" | grep -q "renumbered" && grep -q ": Alpha" .where-were-we/decisions.md && grep -q ": Beta" .where-were-we/decisions.md && ! echo "$out" | grep -q "hand-edited"'

# --- general
cd $T/p2 && ok "general: done/archive run" '$PY done --no-promote >/dev/null; $PY archive >/dev/null; true'
echo "== $pass passed, $fail failed"
rm -rf "$T"
[ $fail = 0 ]
