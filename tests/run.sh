#!/bin/bash
# Run every where-were-we test against this checkout: `bash tests/run.sh`
# Needs git and python3 (macOS or Linux). Each test works in its own temporary
# HOME and git repositories, so nothing outside a temp folder is touched.
set -u
here="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/skill" && ln -s "$here" "$tmp/skill/where-were-we"   # the tests expect <dir>/where-were-we/
fail=0
for t in "$here"/tests/test_*.sh; do
  printf '%-22s ' "$(basename "$t")"
  out="$(bash "$t" "$tmp/skill" "$tmp" 2>/dev/null)"
  echo "$out" | tail -1
  echo "$out" | grep '^FAIL' || true
  echo "$out" | tail -1 | grep -q ' 0 failed' || fail=1
done
exit $fail
