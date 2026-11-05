SKILL=$1/where-were-we; PY="python3 $SKILL/scripts/status.py"
T=$(mktemp -d "$2/tn.XXXX"); pass=0; fail=0
ok(){ if eval "$2"; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1"; fail=$((fail+1)); fi; }
export HOME=$T/home; mkdir -p $HOME; export XDG_CONFIG_HOME=$HOME/.config GIT_CONFIG_GLOBAL=$HOME/.gitconfig
git config --global user.email me@example.com; git config --global user.name me; git config --global init.defaultBranch main
# N1 team's committed STATUS.md
mkdir $T/n1 && cd $T/n1 && git init -q && printf "# Project status\nBeta.\n" > STATUS.md
for a in a b c; do echo $a>>f; git add -A; git -c user.email=$a@x.io commit -qm $a; done
out=$($PY init); rc=$?
ok "N1 init refuses the team's STATUS.md, creates nothing" '[ $rc = 1 ] && echo "$out" | grep -q "belongs to the repository: leave it" && [ ! -e .where-were-we ]'
ok "N1 commands refuse before setup, team file untouched" '! $PY claim "x" >/dev/null && ! $PY done --next y >/dev/null && ! $PY decide z >/dev/null && grep -qx Beta. STATUS.md && [ ! -e .where-were-we ]'
out=$($PY init --path .where-were-we/STATUS.md); rc=$?
ok "N1 --path works, team file untouched" '[ $rc = 0 ] && [ -f .where-were-we/STATUS.md ] && [ "$(cat STATUS.md)" = "$(printf "# Project status\nBeta.")" ] && [ -z "$(git status --porcelain)" ]'
ok "N1 claim/done use the new file" '$PY claim "my task" >/dev/null && grep -q "my task" .where-were-we/STATUS.md && $PY done >/dev/null && ! grep -q "my task" .where-were-we/STATUS.md'
ok "N1 check clean of errors" '! $PY check | grep -q "^error"'
ok "N1 link block points at the new path" '$PY init --link >/dev/null; grep -q "Read .where-were-we/STATUS.md" CLAUDE.local.md'
ok "N1 remove keeps team STATUS.md" '$PY remove --yes >/dev/null; grep -q Beta STATUS.md && [ ! -e .where-were-we ] && [ -z "$(git status --porcelain)" ]'
# own uncommitted notes
mkdir $T/own && cd $T/own && printf "my old notes\n" > STATUS.md
out=$($PY init); rc=$?
ok "own STATUS.md: refuses, suggests moving it in" '[ $rc = 1 ] && echo "$out" | grep -q "move it in"'
mkdir -p .where-were-we/log && mv STATUS.md .where-were-we/log/legacy-2026-11-05-STATUS.md
ok "after moving it in, init works and keeps the legacy log" '$PY init >/dev/null && [ -f STATUS.md ] && [ -f .where-were-we/log/legacy-2026-11-05-STATUS.md ]'
# our-format STATUS.md without config is accepted
mkdir $T/fmt && cd $T/fmt && $PY init >/dev/null && rm -rf .where-were-we
ok "our-format STATUS.md without config: init proceeds" '$PY init | grep -q "already exists, leaving it alone"'
# N2 foreign state folder
mkdir -p $T/n2/.where-were-we && cd $T/n2 && echo x > .where-were-we/other.txt
out=$($PY init); rc=$?
ok "N2 foreign folder: init refuses" '[ $rc = 1 ] && echo "$out" | grep -q "other.txt" && [ ! -e .where-were-we/config.json ]'
# remove keeps user files put inside later
mkdir $T/n3 && cd $T/n3 && $PY init >/dev/null && $PY decide "x" >/dev/null && echo mine > .where-were-we/notes.txt && mkdir .where-were-we/log/img && echo i > .where-were-we/log/img/a.png
out=$($PY remove)
ok "remove plan names kept files" 'echo "$out" | grep -q "kept, as where-were-we did not create them: .where-were-we/log/img/a.png, .where-were-we/notes.txt"'
$PY remove --yes >/dev/null
ok "remove deletes ours, keeps theirs" '[ -f .where-were-we/notes.txt ] && [ -f .where-were-we/log/img/a.png ] && [ ! -e .where-were-we/decisions.md ] && [ ! -e .where-were-we/config.json ] && [ ! -e STATUS.md ]'
# --path validation and ignored when config exists
mkdir $T/p && cd $T/p
ok "--path rejects .." '! $PY init --path ../x.md >/dev/null'
$PY init >/dev/null
ok "--path ignored with existing config" '$PY init --path docs/S.md | grep -q -- "--path ignored"'
echo "== $pass passed, $fail failed"; rm -rf "$T"; [ $fail = 0 ]
