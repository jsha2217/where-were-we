SKILL=$1/where-were-we; PY="python3 $SKILL/scripts/status.py"
T=$(mktemp -d "$2/ta.XXXX"); pass=0; fail=0
ok(){ if eval "$2"; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1"; fail=$((fail+1)); fi; }
export HOME=$T/home; mkdir -p $HOME; export XDG_CONFIG_HOME=$HOME/.config GIT_CONFIG_GLOBAL=$HOME/.gitconfig
git config --global user.email me@example.com; git config --global user.name me
nx(){ python3 - "$1" <<'PY'
import sys; s=open("STATUS.md").read(); s=s.replace("## Next\n","## Next\n- "+sys.argv[1]+"\n",1); open("STATUS.md","w").write(s)
PY
}
L(){ grep -n "$1" STATUS.md | head -1 | cut -d: -f1; }
cd $T && mkdir app && cd app && git init -q && $PY init --shared >/dev/null
nx "owner ops@acme-shop.kr, key AKIAABCDEFGHIJKLMNOP"; n=$(L AKIA)
out=$($PY allow STATUS.md:$n); rc=$?
ok "mixed line without --kind is refused" '[ $rc = 1 ] && echo "$out" | grep -q "more than one kind" && echo "$out" | grep -q -- "--kind email"'
ok "nothing stored after refusal" 'python3 -c "import json,sys;sys.exit(json.load(open(\".where-were-we/config.json\"))[\"allow\"]!=[])"'
out=$($PY allow STATUS.md:$n --kind email)
ok "--kind email allows only the email" 'echo "$out" | grep -q "still flagged on that line: API key or token"'
out=$($PY check --ci); rc=$?
ok "key still an error" '[ $rc = 1 ] && echo "$out" | grep -q "(API key or token)" && ! echo "$out" | grep -q "email address"'
ok "entry has kind/where/date, no value" 'grep -q "\"kind\": \"email address\"" .where-were-we/config.json && grep -q "\"where\": \"STATUS.md:$n\"" .where-were-we/config.json && grep -q "\"date\"" .where-were-we/config.json && ! grep -q "ops@\|AKIA" .where-were-we/config.json'
ok "--kind not on line is refused" '! $PY allow STATUS.md:$n --kind phone >/dev/null'
ok "bad --kind rejected by argparse" '! $PY allow STATUS.md:$n --kind bogus >/dev/null 2>&1'
$PY allow STATUS.md:$n --kind email >/dev/null
ok "repeat allow adds no duplicate" '[ $(grep -c "\"id\"" .where-were-we/config.json) = 1 ]'
$PY allow STATUS.md:$n --kind key >/dev/null
ok "check passes after both allowed" '$PY check --ci >/dev/null'
out=$($PY allow --list)
ok "--list shows two entries" '[ $(echo "$out" | wc -l) -eq 2 ] && echo "$out" | grep -q "API key or token"'
id=$(echo "$out" | grep "API key" | cut -d" " -f1)
ok "--remove drops one" '$PY allow --remove $id | grep -q "removed" && $PY check --ci | grep -q "API key or token" && $PY allow --list | grep -q "email address"'
ok "--remove unknown id fails" '! $PY allow --remove 0000000000000000 >/dev/null'
nx "single ops2@acme-shop.kr"
ok "single-kind line needs no --kind" '$PY allow STATUS.md:$(L ops2) | grep -q "allowed on the user"'
python3 -c 'import json;p=".where-were-we/config.json";c=json.load(open(p));c["allow"]=["0a06fe4f8a57e5fe"];json.dump(c,open(p,"w"))'
ok "malformed allow is warned and ignored" '$PY check | grep -q "setting .allow. must be"; ! $PY check --ci >/dev/null'
ok "--reset clears" '$PY allow --reset | grep -q "cleared" && $PY allow --list | grep -q "nothing is allowed"'
echo "== $pass passed, $fail failed"; rm -rf "$T"; [ $fail = 0 ]
