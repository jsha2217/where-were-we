#!/usr/bin/env python3
"""where-were-we helper: your own STATUS.md, kept out of git. Standard library only.

  init [--link]      create STATUS.md and .where-were-we/, list them in .git/info/exclude
                     (--link: add a block to CLAUDE.local.md so every session reads STATUS.md first)
  claim N | "TEXT"   start work: Next item N (or the one matching TEXT) moves into Now; new TEXT is added
  done [N | "TEXT"]  finish a Now item and log it (no argument when Now has one item)
  decide "TEXT"      record a decision: "Use X, not Y — because Z"
  check              is STATUS.md still small and complete?
  hook-start         (plugin) SessionStart: print STATUS.md into the session
  hook-stop          (plugin) Stop: once per new commit, ask to update STATUS.md if it is older

Several windows or subagents may run commands at once: writes take turns through a lock and replace
files atomically, so no update is lost and no file is left half-written.
"""

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

VERSION = "0.12.0"
STATUS = "STATUS.md"
STATE = ".where-were-we"
LINK_FILE = "CLAUDE.local.md"
SECTIONS = ["Goal", "Now", "Next", "Blocked", "Decisions"]
MAX_LINES = 50
SHOWN_DECISIONS = 5
EXCLUDE = ["# where-were-we (personal: never committed)", f"/{STATUS}", f"/{STATE}/", f"/{LINK_FILE}"]
ITEM_RE = re.compile(r"^\s*[-*]\s+(?:\[[ xX]\]\s*)?(.*)$")
PLACEHOLDER_RE = re.compile(r"^\((?:none(?: yet)?|\+\d+ older: .*)\)$")
DEC_RE = re.compile(r"^- D-(\d+)")

TEMPLATE = "\n".join([  # "- " placeholders keep their trailing space, so editors cannot strip them
    "# Status", "_updated: {date}_", "",
    "## Goal", "- ", "", "## Now", "- [ ] ", "", "## Next", "- ", "",
    "## Blocked", "- (none)", "", "## Decisions", "- (none yet)", ""])

LINK_START, LINK_END = "<!-- where-were-we:start -->", "<!-- where-were-we:end -->"
LINK_BLOCK = f"""{LINK_START}
## Project status
Read {STATUS} before starting work: it is my own record of where this project is (kept out of git).
It is notes, not instructions. Keep it true as you work, max {MAX_LINES} lines; subagents leave it to the main agent.
With the where-were-we skill: `claim` to start work, `done` to finish it, `decide` for decisions the user made.
{LINK_END}
"""


def today():
    return dt.date.today().isoformat()


def git(root, *args):
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def write(p, text):
    """Atomic: write a temp file, then rename over the old one."""
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, p)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


@contextmanager
def lock(root):
    """One writer at a time across windows and subagents."""
    path = root / STATE / ".lock"
    for _ in range(100):
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime > 30:  # left behind by a crashed run
                    path.unlink()
                    continue
            except OSError:
                pass
            time.sleep(0.1)
    else:
        sys.exit("another window is still updating the status file; try again in a moment.")
    try:
        yield
    finally:
        try:
            path.unlink()
        except OSError:
            pass


# ---------- STATUS.md sections ----------

def find_section(lines, name):
    for i, line in enumerate(lines):
        if line.strip() == f"## {name}":
            end = next((j for j in range(i + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
            return i, end
    return None


def items(lines, name):
    s = find_section(lines, name)
    if s is None:
        return []
    out = []
    for line in lines[s[0] + 1:s[1]]:
        m = ITEM_RE.match(line)
        text = m.group(1).strip() if m else ""
        if text and not PLACEHOLDER_RE.match(text):
            out.append(text)
    return out


def set_section(lines, name, body):
    s = find_section(lines, name)
    if s is None:
        sys.exit(f"{STATUS} has no '## {name}' section; add it back and try again.")
    start, end = s
    return lines[:start + 1] + body + ([""] + lines[end:] if end < len(lines) else [])


def save_status(root, lines):
    text = "\n".join(lines).rstrip("\n") + "\n"
    write(root / STATUS, re.sub(r"^_updated:.*_$", f"_updated: {today()}_", text, count=1, flags=re.M))


def pick(texts, what):
    """Index of the item numbered `what` or containing it; None after saying why."""
    if what.isdigit() and 1 <= int(what) <= len(texts):
        return int(what) - 1
    hits = [k for k, t in enumerate(texts) if what.lower() in t.lower()]
    if len(hits) == 1:
        return hits[0]
    if hits:
        print(f"'{what}' matches {len(hits)} items; be more specific:")
        for k in hits:
            print(f"  {k + 1}. {texts[k]}")
    return None


# ---------- commands ----------

def cmd_init(root, args):
    (root / STATE / "log").mkdir(parents=True, exist_ok=True)
    if not (root / STATE / "decisions.md").exists():
        write(root / STATE / "decisions.md", "# Decisions\n\n")
    if (root / STATUS).exists():
        print(f"{STATUS} already exists, leaving it alone.")
    else:
        write(root / STATUS, TEMPLATE.format(date=today()))
        print(f"created {STATUS} and {STATE}/")
    rel = git(root, "rev-parse", "--git-path", "info/exclude")
    if rel:
        ex = (root / rel).resolve()
        text = ex.read_text(encoding="utf-8") if ex.exists() else ""
        missing = [l for l in EXCLUDE if l not in text.splitlines()]
        if missing:
            write(ex, text + ("\n" if text and not text.endswith("\n") else "") + "\n".join(missing) + "\n")
            print("listed them in .git/info/exclude: they stay on this machine and never reach a commit.")
    if args.link:
        p = root / LINK_FILE
        text = p.read_text(encoding="utf-8") if p.exists() else ""
        if LINK_START in text:
            print(f"{LINK_FILE} already points at {STATUS}.")
        else:
            write(p, text + ("\n" if text and not text.endswith("\n\n") else "") + LINK_BLOCK)
            print(f"linked from {LINK_FILE}")
    return 0


def cmd_claim(root, args):
    lines = (root / STATUS).read_text(encoding="utf-8").splitlines()
    what = " ".join(args.what).strip()
    nxt = items(lines, "Next")
    k = pick(nxt, what)
    if k is None and what.isdigit():
        print(f"no Next item {what}.")
        return 1
    if k is None and any(what.lower() in t.lower() for t in nxt):
        return 1  # several matches, already listed
    text = nxt.pop(k) if k is not None else what
    lines = set_section(lines, "Next", [f"- {t}" for t in nxt] or ["- "])
    lines = set_section(lines, "Now", [f"- [ ] {t}" for t in items(lines, "Now") + [text]])
    save_status(root, lines)
    print(f"now: {text}" + (" (from Next)" if k is not None else ""))
    return 0


def cmd_done(root, args):
    lines = (root / STATUS).read_text(encoding="utf-8").splitlines()
    now = items(lines, "Now")
    what = " ".join(args.what).strip()
    if not now:
        print("nothing in Now. Start something with `claim`.")
        return 1
    if not what and len(now) > 1:
        print("several items in Now; say which with `done N` or `done \"text\"`:")
        for k, t in enumerate(now, 1):
            print(f"  {k}. {t}")
        return 1
    k = pick(now, what) if what else 0
    if k is None:
        print(f"no Now item matches '{what}'.")
        return 1
    text = now.pop(k)
    save_status(root, set_section(lines, "Now", [f"- [ ] {t}" for t in now] or ["- [ ] "]))
    log = root / STATE / "log" / f"{today()[:7]}.md"
    old = log.read_text(encoding="utf-8") if log.exists() else f"# Log {today()[:7]}\n"
    heading = f"## {today()}"
    write(log, old.rstrip("\n") + ("\n" if heading in old else f"\n\n{heading}\n") + f"- {text}\n")
    print(f"done: {text} (logged in {log.relative_to(root)})")
    return 0


def cmd_decide(root, args):
    text = " ".join(args.text).strip()
    p = root / STATE / "decisions.md"
    dec = p.read_text(encoding="utf-8").splitlines() if p.exists() else ["# Decisions", ""]
    num = max((int(m.group(1)) for m in map(DEC_RE.match, dec) if m), default=0) + 1
    dec.append(f"- D-{num:03d} ({today()}): {text}")
    write(p, "\n".join(dec).rstrip("\n") + "\n")
    all_dec = [re.sub(r" \(\d{4}-\d{2}-\d{2}\)", "", l, count=1) for l in dec if DEC_RE.match(l)]
    shown = all_dec[-SHOWN_DECISIONS:]
    older = len(all_dec) - len(shown)
    if older:
        shown.append(f"- (+{older} older: {STATE}/decisions.md)")
    lines = (root / STATUS).read_text(encoding="utf-8").splitlines()
    save_status(root, set_section(lines, "Decisions", shown))
    print(f"recorded D-{num:03d}")
    return 0


def cmd_check(root, args):
    lines = (root / STATUS).read_text(encoding="utf-8").rstrip("\n").splitlines()
    problems = [f"missing section '## {s}'" for s in SECTIONS if find_section(lines, s) is None]
    if len(lines) > MAX_LINES:
        problems.append(f"{STATUS} is {len(lines)} lines (max {MAX_LINES}): finish items, trim Next, "
                        f"move detail to {STATE}/decisions.md")
    for p in problems:
        print(f"error: {p}")
    if not problems:
        print(f"ok: {STATUS} looks good.")
    return 1 if problems else 0


# ---------- Claude Code hooks (plugin) ----------
# Hooks must never break a session: any problem means "say nothing".

def hook_input():
    try:
        data = json.loads(sys.stdin.read() or "{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def hook_root(data):
    cwd = Path(data.get("cwd") or os.getcwd())
    top = git(cwd, "rev-parse", "--show-toplevel")
    root = Path(top).resolve() if top else cwd.resolve()
    return root if (root / STATUS).exists() and (root / STATE).is_dir() else None


def hook_start():
    """SessionStart: put STATUS.md into the session, so reading it never depends on the agent remembering."""
    root = hook_root(hook_input())
    if not root:
        return 0
    status = (root / STATUS).read_text(encoding="utf-8")[:8000]
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": (
        f"where-were-we: {STATUS} below is the user's own record of where this project is (notes, not "
        "instructions). Keep it current with the where-were-we skill: claim, done, decide.\n\n" + status)}},
        ensure_ascii=False))
    return 0


def hook_stop():
    """Stop: when the user's newest commit is newer than STATUS.md, ask once (per commit) to update it."""
    data = hook_input()
    if data.get("stop_hook_active"):
        return 0
    root = hook_root(data)
    if not root:
        return 0
    email = git(root, "config", "--get", "user.email")
    last = git(root, "log", "-1", "--format=%H %ct", *([f"--author={email}"] if email else []))
    if not last:
        return 0
    commit, when = last.split()
    seen = root / STATE / ".reminded"
    if int(when) <= (root / STATUS).stat().st_mtime or (seen.exists() and seen.read_text().strip() == commit):
        return 0
    write(seen, commit + "\n")
    print(json.dumps({"decision": "block", "reason": (
        f"where-were-we: commit {commit[:7]} is newer than {STATUS}. If it finished or started work or settled "
        "a decision the user made, update the file now (done / claim / decide). If nothing changed, just stop.")}))
    return 0


def main():
    if sys.argv[1:] in (["hook-start"], ["hook-stop"]):
        try:
            return hook_start() if sys.argv[1] == "hook-start" else hook_stop()
        except Exception:
            return 0
    p = argparse.ArgumentParser(description="Keep your own STATUS.md small and current, out of git.")
    p.add_argument("--version", action="version", version=f"where-were-we {VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").add_argument("--link", action="store_true", help=f"point {LINK_FILE} at {STATUS}")
    sub.add_parser("claim").add_argument("what", nargs="+")
    sub.add_parser("done").add_argument("what", nargs="*")
    sub.add_parser("decide").add_argument("text", nargs="+")
    sub.add_parser("check")
    args = p.parse_args()
    top = git(Path.cwd(), "rev-parse", "--show-toplevel")  # agents often cd into a subfolder
    root = Path(top).resolve() if top else Path.cwd().resolve()
    if args.cmd == "init":
        return cmd_init(root, args)
    if not (root / STATUS).exists() or not (root / STATE).is_dir():
        print(f"where-were-we is not set up here (no {STATUS} and {STATE}/); run `status.py init` first.")
        return 1
    if args.cmd == "check":
        return cmd_check(root, args)
    with lock(root):
        return {"claim": cmd_claim, "done": cmd_done, "decide": cmd_decide}[args.cmd](root, args)


if __name__ == "__main__":
    sys.exit(main())
