#!/usr/bin/env python3
"""where-were-we helper: a STATUS.md kept local or committed to Git. Standard library only.

  init [--local | --git] [--link]
                     choose whether status, decisions and logs can be committed
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
from contextlib import contextmanager, redirect_stdout
import io
from pathlib import Path

VERSION = "0.13.0"
STATUS = "STATUS.md"
STATE = ".where-were-we"
DONE_PENDING = ".done-pending.json"
DECIDE_PENDING = ".decide-pending.json"
LINK_FILE = "CLAUDE.local.md"
SECTIONS = ["Goal", "Now", "Next", "Blocked", "Decisions"]
MAX_LINES = 50
SHOWN_DECISIONS = 5
LEGACY_EXCLUDE = ["# where-were-we (personal: never committed)", f"/{STATUS}", f"/{STATE}/", f"/{LINK_FILE}"]
EXCLUDE_HEADERS = {mode: f"# where-were-we ({mode})" for mode in ("local", "git")}
# Headers written by 0.13.0 before the modes were renamed; still read, replaced on the next init.
OLD_HEADERS = {"# where-were-we (personal)": "local", "# where-were-we (shared)": "git"}
EXCLUDE_END = "# /where-were-we"
LOCAL_EXCLUDE = [f"/{LINK_FILE}", f"/.{STATUS}.*.tmp", f"/.{LINK_FILE}.*.tmp",
                 f"/{STATE}/.lock", f"/{STATE}/.reminded", f"/{STATE}/{DONE_PENDING}",
                 f"/{STATE}/{DECIDE_PENDING}",
                 f"/{STATE}/**/.*.tmp"]
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
Read {STATUS} before starting work: it records where this project's work stands.
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


def status_text(lines):
    text = "\n".join(lines).rstrip("\n") + "\n"
    return re.sub(r"^_updated:.*_$", f"_updated: {today()}_", text, count=1, flags=re.M)


def save_status(root, lines):
    write(root / STATUS, status_text(lines))


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

def exclude_path(root):
    rel = git(root, "rev-parse", "--git-path", "info/exclude")
    return (root / rel).resolve() if rel else None


def configured_mode(text):
    for line in reversed(text.splitlines()):
        for mode, header in EXCLUDE_HEADERS.items():
            if line == header:
                return mode
        if line in OLD_HEADERS:
            return OLD_HEADERS[line]
        if line == LEGACY_EXCLUDE[0]:
            return "local"
    return None


def exclude_text(text, mode):
    """Replace only our marked rules, preserving the user's other exclusions."""
    lines = text.splitlines(keepends=True)
    kept = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\r\n")
        if line in EXCLUDE_HEADERS.values() or line in OLD_HEADERS:
            end = next((j for j in range(i + 1, len(lines))
                        if lines[j].rstrip("\r\n") == EXCLUDE_END), None)
            if end is None:
                sys.exit("unfinished where-were-we block in info/exclude; repair it before setup.")
            i = end + 1
        elif line == LEGACY_EXCLUDE[0]:
            i += 1
            while i < len(lines) and lines[i].rstrip("\r\n") in LEGACY_EXCLUDE[1:]:
                i += 1
        else:
            kept.append(lines[i])
            i += 1
    rules = ([f"/{STATUS}", f"/{STATE}/"] if mode == "local" else []) + LOCAL_EXCLUDE
    prefix = "".join(kept)
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    return prefix + "\n".join([EXCLUDE_HEADERS[mode], *rules, EXCLUDE_END, ""])


def ensure_git_runtime_excludes(root):
    """A cloned, committed status still needs local locks and recovery files ignored."""
    path = exclude_path(root)
    if path is None:
        return
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    mode = configured_mode(old)
    if mode == "git" or (mode is None and git(root, "ls-files", "--", STATUS, f"{STATE}/")):
        updated = exclude_text(old, "git")
        if updated != old:
            write(path, updated)


def choose_mode():
    print("Include work records in Git?\n"
          "  1. git: commit them; other people and computers pick up status, decisions and logs.\n"
          "  2. local: keep them on this computer only, never in a commit.")
    if not sys.stdin.isatty():
        print("Choose with `init --git` or `init --local`.")
        return None
    try:
        while True:
            answer = input("Choose 1 (git) or 2 (local): ").strip().lower()
            if answer in ("1", "git", "yes", "y"):
                return "git"
            if answer in ("2", "local", "no", "n"):
                return "local"
    except (EOFError, KeyboardInterrupt):
        print("\nNo choice made; setup cancelled.")
        return None


def cmd_init(root, args):
    ex = exclude_path(root)
    old_exclude = ex.read_text(encoding="utf-8") if ex and ex.exists() else ""
    tracked = git(root, "ls-files", "--", STATUS, f"{STATE}/") if ex else ""
    mode = args.mode or configured_mode(old_exclude)
    if mode is None and tracked:
        mode = "git"
    if mode is None and ex is None and (root / STATUS).exists() and (root / STATE).is_dir():
        mode = "local"
    mode = mode or choose_mode()
    if mode is None:
        return 1
    if mode == "git" and ex is None:
        print("--git needs a Git repository; create one first, or choose --local.")
        return 1
    if mode == "local" and tracked:
        print("These work records are already tracked by Git:\n" + tracked)
        print("Use --git to keep committing them, or explicitly stop tracking them before --local. "
              "Setup has not changed the files or Git index.")
        return 1
    if ex:
        updated = exclude_text(old_exclude, mode)
        if updated != old_exclude:
            write(ex, updated)
        if mode == "git":
            # Check actual Git rules: unrelated .gitignore or global rules may still hide the notes.
            paths = [STATUS, f"{STATE}/decisions.md", f"{STATE}/log/{today()[:7]}.md"]
            try:
                check = subprocess.run(["git", "check-ignore", "--no-index", "--", *paths],
                                       cwd=root, capture_output=True, text=True, timeout=10)
            except (OSError, subprocess.SubprocessError):
                write(ex, old_exclude)
                raise
            if check.returncode != 1:
                write(ex, old_exclude)
                print("--git setup could not make the work records visible to Git. "
                      "Review the existing ignore rules; they were left unchanged.")
                print(check.stdout or check.stderr)
                return 1
    (root / STATE / "log").mkdir(parents=True, exist_ok=True)
    if not (root / STATE / "decisions.md").exists():
        write(root / STATE / "decisions.md", "# Decisions\n\n")
    if (root / STATUS).exists():
        print(f"{STATUS} already exists, leaving it alone.")
    else:
        write(root / STATUS, TEMPLATE.format(date=today()))
        print(f"created {STATUS} and {STATE}/")
    if mode == "git":
        print("Work records can be included in Git. Commit and push them through your usual workflow.")
        print("You can ask to keep them out of Git at any time.")
    else:
        print("Local mode: work records stay on this computer" + (", excluded through info/exclude." if ex else "."))
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


def recover_pending(root, command):
    """Finish an interrupted done/decide without duplicating records or overwriting edits.

    Called under the writer lock, before another command can change either file.
    The pending file stays until both the record and STATUS.md have been saved.
    """
    pending = root / STATE / (DONE_PENDING if command == "done" else DECIDE_PENDING)
    data = json.loads(pending.read_text(encoding="utf-8"))
    if command == "done":
        month = dt.date.fromisoformat(data["date"]).strftime("%Y-%m")
        record, key = root / STATE / "log" / f"{month}.md", "log"
        message = f"done: {data['task']} (logged in {record.relative_to(root)})"
    else:
        record, key = root / STATE / "decisions.md", "decisions"
        message = f"recorded D-{data['number']:03d}"
    updates = [(record, key), (root / STATUS, "status")]
    current = []
    # Check both files before writing either: a manual edit needs human review.
    for path, key in updates:
        old = path.read_text(encoding="utf-8") if path.exists() else None
        if old not in (data[f"{key}_before"], data[f"{key}_after"]):
            sys.exit(f"{path.relative_to(root)} changed during an unfinished {command}; "
                     f"preserved it and {pending.relative_to(root)} for review. Check both files, finish "
                     f"the {command} by hand if needed, then delete {pending.relative_to(root)}.")
        current.append(old)
    for (path, key), old in zip(updates, current):
        if old != data[f"{key}_after"]:
            write(path, data[f"{key}_after"])
    pending.unlink()
    print(message)
    return 0


def same_request(data, command, args):
    """True when this call repeats the interrupted one, so it must not run a second time."""
    if command == "decide":
        return " ".join(args.text).strip() == data.get("text")
    what = " ".join(args.what).strip()
    if not what:
        return True  # never finish an item nobody named
    now = items(data["status_before"].splitlines(), "Now")
    with redirect_stdout(io.StringIO()):
        k = pick(now, what)
    return k is not None and now[k] == data["task"]


def cmd_done(root, args):
    original = (root / STATUS).read_text(encoding="utf-8")
    lines = original.splitlines()
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
    updated = status_text(set_section(lines, "Now", [f"- [ ] {t}" for t in now] or ["- [ ] "]))
    day = today()
    log = root / STATE / "log" / f"{day[:7]}.md"
    old = log.read_text(encoding="utf-8") if log.exists() else None
    body = old if old is not None else f"# Log {day[:7]}\n"
    heading = f"## {day}"
    logged = body.rstrip("\n") + ("\n" if heading in body else f"\n\n{heading}\n") + f"- {text}\n"
    # Save the intent first. Recovery always writes the log before removing Now.
    write(root / STATE / DONE_PENDING, json.dumps({
        "task": text, "date": day,
        "status_before": original, "status_after": updated,
        "log_before": old, "log_after": logged,
    }, ensure_ascii=False) + "\n")
    return recover_pending(root, "done")


def cmd_decide(root, args):
    text = " ".join(args.text).strip()
    original = (root / STATUS).read_text(encoding="utf-8")
    p = root / STATE / "decisions.md"
    old = p.read_text(encoding="utf-8") if p.exists() else None
    dec = old.splitlines() if old is not None else ["# Decisions", ""]
    num = max((int(m.group(1)) for m in map(DEC_RE.match, dec) if m), default=0) + 1
    dec.append(f"- D-{num:03d} ({today()}): {text}")
    all_dec = [re.sub(r" \(\d{4}-\d{2}-\d{2}\)", "", l, count=1) for l in dec if DEC_RE.match(l)]
    shown = all_dec[-SHOWN_DECISIONS:]
    older = len(all_dec) - len(shown)
    if older:
        shown.append(f"- (+{older} older: {STATE}/decisions.md)")
    updated = status_text(set_section(original.splitlines(), "Decisions", shown))
    write(root / STATE / DECIDE_PENDING, json.dumps({
        "number": num, "text": text,
        "decisions_before": old, "decisions_after": "\n".join(dec).rstrip("\n") + "\n",
        "status_before": original, "status_after": updated,
    }, ensure_ascii=False) + "\n")
    return recover_pending(root, "decide")


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
    status = (root / STATUS).read_text(encoding="utf-8")
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
    ensure_git_runtime_excludes(root)
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
    p = argparse.ArgumentParser(description="Keep STATUS.md small and current, kept local or committed to Git.")
    p.add_argument("--version", action="version", version=f"where-were-we {VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)
    init = sub.add_parser("init")
    init.add_argument("--link", action="store_true", help=f"point {LINK_FILE} at {STATUS}")
    modes = init.add_mutually_exclusive_group()
    modes.add_argument("--local", dest="mode", action="store_const", const="local",
                       help="exclude work records from Git")
    modes.add_argument("--git", dest="mode", action="store_const", const="git",
                       help="let work records be committed for handoff")
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
    ensure_git_runtime_excludes(root)
    with lock(root):
        for command, filename in (("done", DONE_PENDING), ("decide", DECIDE_PENDING)):
            pending = root / STATE / filename
            if pending.exists():
                data = json.loads(pending.read_text(encoding="utf-8"))
                recover_pending(root, command)
                if args.cmd == command and same_request(data, command, args):
                    return 0  # A retry finishes only the pending operation.
        return {"claim": cmd_claim, "done": cmd_done, "decide": cmd_decide}[args.cmd](root, args)


if __name__ == "__main__":
    sys.exit(main())
