SKILL=$1/where-were-we; PY="python3 $SKILL/scripts/status.py"
T=$(mktemp -d "$2/t2.XXXX"); pass=0; fail=0
ok(){ if eval "$2"; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1"; fail=$((fail+1)); fi; }
export HOME=$T/home; mkdir -p $HOME; export XDG_CONFIG_HOME=$HOME/.config
export GIT_CONFIG_GLOBAL=$HOME/.gitconfig; git config --global user.email me@example.com; git config --global user.name me
# --- 2 offer scanning
mkdir -p $HOME/Desktop/myapp/.where-were-we $HOME/Documents/doc-app/.where-were-we $HOME/작업/cool/.where-were-we $HOME/dev/svc/.where-were-we
for d in Desktop/myapp Documents/doc-app 작업/cool dev/svc; do echo '{}' > $HOME/$d/.where-were-we/config.json; done
cd $HOME; out=$($PY offer)
ok "2 home finds any-named folders (dev, 작업)" 'echo "$out" | grep -q "elsewhere:" && echo "$out" | grep -q "작업/cool" && echo "$out" | grep -q "dev/svc"'
ok "2 home skips Desktop/Documents" '! echo "$out" | grep -q "myapp\|doc-app"'
cd $HOME/Desktop; ok "2 inside Desktop finds myapp" '$PY offer | grep -q "elsewhere: myapp"'
rm -rf $HOME/dev $HOME/작업; cd $HOME; out=$($PY offer)
ok "2 home with nothing outside protected: hint about find" 'echo "$out" | grep -q "were not searched" && echo "$out" | grep -q "not a project folder"'
for i in $(seq 8); do mkdir -p $HOME/w/p$i/.where-were-we; echo '{}' > $HOME/w/p$i/.where-were-we/config.json; done
ok "2 long list capped at 5" '$PY offer | grep -q "and 3 more"'
# --- 3 path change, personal
P=$T/c; mkdir -p $P/docs && cd $P && git init -q && $PY init >/dev/null
echo "/my-own-ignore" >> .git/info/exclude
python3 -c 'import json;p=".where-were-we/config.json";c=json.load(open(p));c["path"]="docs/STATUS.md";json.dump(c,open(p,"w"),indent=2)'
cp STATUS.md docs/STATUS.md
ok "3p check warns new path not excluded" '$PY check | grep -q "not in .git/info/exclude"'
$PY init >/dev/null
ok "3p new path excluded, old kept while old file exists" 'grep -qx "/docs/STATUS.md" .git/info/exclude && grep -qx "/STATUS.md" .git/info/exclude'
ok "3p docs/STATUS.md not in git status" '[ -z "$(git status --porcelain)" ]'
ok "3p user's own exclude line survives" 'grep -qx "/my-own-ignore" .git/info/exclude'
ok "3p remove keeps user's line" '$PY remove --yes >/dev/null; grep -qx "/my-own-ignore" .git/info/exclude && ! grep -q "where-were-we\|/docs/STATUS.md" .git/info/exclude'
echo "== $pass passed, $fail failed"; rm -rf "$T"; [ $fail = 0 ]
