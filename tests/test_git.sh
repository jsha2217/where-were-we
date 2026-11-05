#!/bin/bash
# The files stay out of git: branches, worktrees, staleness, migrating from an older shared setup.
SKILL=$1/where-were-we; PY="python3 $SKILL/scripts/status.py"
T=$(mktemp -d "$2/tg.XXXX"); pass=0; fail=0
ok(){ if eval "$2"; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1"; fail=$((fail+1)); fi; }
export HOME=$T/home; mkdir -p $HOME; export XDG_CONFIG_HOME=$HOME/.config GIT_CONFIG_GLOBAL=$HOME/.gitconfig
git config --global user.email me@example.com; git config --global user.name me; git config --global init.defaultBranch main

# 1 branches: the files never move
mkdir $T/b && cd $T/b && git init -q && echo a > a && git add a && git commit -qm a && $PY init --link >/dev/null
ok "1 git status clean after init --link" '[ -z "$(git status --porcelain)" ]'
$PY claim "my work" >/dev/null
git checkout -qb feature && echo b > b && git add b && git commit -qm b && git checkout -q main
ok "1 branch switch keeps STATUS.md as is" 'grep -q "my work" STATUS.md'
git merge -q --no-edit feature
ok "1 merge leaves STATUS.md alone" 'grep -q "my work" STATUS.md && [ -z "$(git status --porcelain)" ]'
ok "1 git add -A never picks the files up" 'git add -A && [ -z "$(git diff --cached --name-only)" ]'

# 2 linked worktree uses the main worktree's files
git worktree add -q $T/b-wt -b wt 2>/dev/null
cd $T/b-wt
ok "2 worktree has no copy of its own" '[ ! -e STATUS.md ]'
ok "2 claim in the worktree updates the main file" '$PY claim "from worktree" >/dev/null && grep -q "from worktree" $T/b/STATUS.md'
ok "2 check says where the file is" '$PY check | grep -q "shared from the main worktree"'

# 3 init inside a fresh worktree of an un-set-up repo excludes in the shared .git
mkdir $T/c && cd $T/c && git init -q && echo a > a && git add a && git commit -qm a && git worktree add -q $T/c-wt -b x 2>/dev/null
cd $T/c-wt && $PY init >/dev/null
ok "3 worktree init: exclude lands where git reads it" 'grep -qx "/STATUS.md" $T/c/.git/info/exclude && [ -z "$(git status --porcelain)" ]'

# 4 staleness: your commits since the file was edited
mkdir $T/s && cd $T/s && git init -q && $PY init >/dev/null && touch -t 202001010000 STATUS.md
for i in 1 2 3 4 5; do echo $i>>c; git add c; GIT_COMMITTER_DATE=2021-01-01T00:00:00 git commit -qm c$i; done
ok "4 staleness warning" '$PY check | grep -q "5 of your commits since STATUS.md"'
$PY claim "fresh" >/dev/null
ok "4 editing clears it" '! $PY check | grep -q "of your commits"'

# 5 migrating an older shared setup
mkdir $T/m && cd $T/m && git init -q && $PY init >/dev/null
python3 -c 'import json;p=".where-were-we/config.json";c=json.load(open(p));c.update(team=False,personal=False,allow=[]);json.dump(c,open(p,"w"),indent=2)'
printf '*.png binary\n.where-were-we/decisions.md merge=union\nSTATUS.md merge=where-were-we\n' > .gitattributes
cp $SKILL/scripts/status.py .where-were-we/status.py
printf '# Team\n\n<!-- where-were-we:start -->\n## Project status\nold\n<!-- where-were-we:end -->\n' > CLAUDE.md
git config merge.where-were-we.driver "x"; git config where-were-we.handle mk
sed -i '' '/where-were-we/d' .git/info/exclude
git add -f -A && git commit -qm shared
ok "5 check flags the leftovers and tracked files" 'out=$($PY check); echo "$out" | grep -q "leftovers" && echo "$out" | grep -q "still tracked"'
out=$($PY init)
ok "5 init drops old settings" 'echo "$out" | grep -q "dropped old" && ! grep -q "\"team\"\|\"allow\"" .where-were-we/config.json'
ok "5 init cleans .gitattributes, keeps the user line" 'grep -qx "\*.png binary" .gitattributes && ! grep -q "merge=" .gitattributes'
ok "5 init removes helper copy and git config" '[ ! -e .where-were-we/status.py ] && ! git config --get where-were-we.handle && ! git config --get merge.where-were-we.driver'
ok "5 init says how to untrack" 'echo "$out" | grep -q "git rm -r --cached STATUS.md .where-were-we"'
ok "5 init points at the old block in CLAUDE.md" 'echo "$out" | grep -q "CLAUDE.md still hold"'
$PY init --link >/dev/null
ok "5 init --link moves the block to CLAUDE.local.md" '! grep -q where-were-we CLAUDE.md && grep -q "# Team" CLAUDE.md && grep -q where-were-we CLAUDE.local.md'
git rm -rq --cached STATUS.md .where-were-we && git commit -qam untrack
ok "5 after untracking, nothing shows" '[ -z "$(git status --porcelain | grep -v "CLAUDE.md\|gitattributes")" ] && ! $PY check | grep -q "tracked\|leftovers"'

# 6 link block refreshed in place, the rest of the file kept
mkdir $T/lk && cd $T/lk && git init -q && printf "# Mine\n\nintro\n" > CLAUDE.local.md && $PY init --link >/dev/null && printf "\n## After\nkeep me last\n" >> CLAUDE.local.md
sed -i '' 's/^It is notes, not instructions\.$/It is notes./' CLAUDE.local.md
out=$($PY init)
ok "6 outdated block refreshed" 'echo "$out" | grep -q "updated the Project status block in CLAUDE.local.md" && grep -q "It is notes, not instructions." CLAUDE.local.md'
ok "6 refresh keeps the user's layout" 'tail -1 CLAUDE.local.md | grep -q "keep me last" && head -1 CLAUDE.local.md | grep -q "# Mine"'
ok "6 no change, no message" '! $PY init | grep -q "updated the Project status block"'

# 7 remove cleans everything it made
cd $T/b && $PY remove --yes >/dev/null
ok "7 remove: files, block and exclude lines gone" '[ ! -e STATUS.md ] && [ ! -e .where-were-we ] && [ ! -e CLAUDE.local.md ] && ! grep -q where-were-we .git/info/exclude'

echo "== $pass passed, $fail failed"; rm -rf "$T"; [ $fail = 0 ]
