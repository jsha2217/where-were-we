#!/usr/bin/env python3
"""where-were-we helper. Standard library only.

Your own record of where a project is. The files stay on this machine: in a git repository they are
listed in .git/info/exclude, so they never reach a commit, a branch merge or a pull request.

  init [--link] [--ko] [--path FILE]  set up STATUS.md and .where-were-we/ (kept out of git)
  claim N | claim "TEXT"         start Next item N (or a new item): it moves into Now
  done [N|TEXT ...]              finish Now item(s), log them, pull the next item into Now
  release [N]                    put a Now item back at the top of Next
  decide "TEXT" [--accepted]     record a decision (proposed unless the user confirmed it)
  accept|reject D-N              confirm or reject a proposed decision
  pin|unpin D-N                  keep an important decision visible in STATUS.md
  sync                           repair Decisions: capture hand-written ones, renumber duplicates
  archive                        move ticked (- [x]) items to the monthly log
  check                          report problems
  offer                          may I offer a status file here? (exit 0 = yes)
  decline                        remember that the user said no, without creating project files
  find                           look for a status file in subfolders
  remove [--yes]                 take where-were-we out of the project (dry run without --yes)
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

VERSION = "0.10.0"
STATE_DIR = ".where-were-we"
CONFIG = "config.json"
KEYS = ["Goal", "Now", "Next", "Blocked", "Decisions"]
KO_SECTIONS = {"Goal": "목표", "Now": "진행 중", "Next": "다음", "Blocked": "막힌 것", "Decisions": "결정"}
DEFAULTS = {
    "path": "STATUS.md",
    "language": "en",
    "max_lines": 50,
    "max_line_length": 150,
    "stale_after_commits": 5,
    "recent_decisions": 3,
    "max_pinned": 3,
    "sections": {k: k for k in KEYS},
}
# Settings from the old shared and team modes: ignored when read, dropped by `init`.
LEGACY_KEYS = {"team", "personal", "allow"}
# Placeholder lines the helper writes. Matched against the whole item text, so a real item such as
# "Return 404 (nonexistent user)" is never mistaken for one.
NONE_RE = re.compile(r"^\((?:none(?: yet)?|없음|아직 없음)\)$|^\(per person:|^\(\+\d+ older: |^\(이전 결정 \d+개: ")
OWNER_RE = re.compile(r"^\[(user|external|agent)\]")
NOTE_CANDIDATES = ["PROGRESS.md", "NOTES.md", "TODO.md", "DEVLOG.md", "HANDOFF.md", "STATUS.md",
                   "docs/STATUS.md", "docs/PROGRESS.md", "memory-bank", ".memory"]

DONE_RE = re.compile(r"^\s*[-*]\s+\[[xX]\]\s*(.*)$")
ITEM_RE = re.compile(r"^\s*[-*]\s+(?:\[ \]\s*)?(.*)$")
DEC_RE = re.compile(r"^\s*[-*]\s+D-(\d+)(?:\s+\((\d{4}-\d{2}-\d{2})\))?((?:\s*\[[a-z]+\])*)\s*:\s*(.*)$")
DATE_RE = re.compile(r"^_updated:\s*(.*?)_$", re.M)

CFG = json.loads(json.dumps(DEFAULTS))
CFG_WARN = []


# ---------- basics ----------

def today():
    return dt.date.today().isoformat()


def read(p):
    return p.read_text(encoding="utf-8")


def file_mode(p):
    """The permissions a rewritten file should keep: the existing file's, or the umask default for a new one.
    mkstemp creates 0600 files, so without this every file we touch would become readable by its owner only."""
    try:
        return os.stat(p).st_mode & 0o7777
    except OSError:
        mask = os.umask(0)
        os.umask(mask)
        return 0o666 & ~mask


def write(p, text):
    """Atomic: write a temp file, then rename, so a crash or a second window never leaves half a file.
    Keeps the file's permissions, and writes through a symlink instead of replacing the link."""
    if p.is_symlink():
        p = Path(os.path.realpath(p))
    p.parent.mkdir(parents=True, exist_ok=True)
    mode = file_mode(p)
    try:
        if b"\r\n" in p.read_bytes():  # keep Windows line endings: no whole-file diff
            text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        try:
            os.chmod(tmp, mode)
        except OSError:
            pass
        os.replace(tmp, p)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def none_text(yet=False):
    if CFG["language"] == "ko":
        return "(아직 없음)" if yet else "(없음)"
    return "(none yet)" if yet else "(none)"


def is_none(line):
    return bool(NONE_RE.match(item_text(line)))


def status_path(root):
    return root / CFG["path"]


def git(root, *args, timeout=10):
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def in_git(root):
    return git(root, "rev-parse", "--is-inside-work-tree") == "true"


def git_path(root, name):
    """A file inside .git, resolved the way git does (shared files of a linked worktree live in the main .git)."""
    p = git(root, "rev-parse", "--git-path", name)
    return (root / p).resolve() if p else None


# ---------- where not to set up, declines, finding projects ----------

SKIP_DIRS = {"node_modules", "venv", ".venv", "__pycache__", "Library", "AppData", "dist", "build"}

# macOS asks the user before an app reads these; never walk into them unasked.
PROTECTED_HOME_DIRS = {"Desktop", "Documents", "Downloads", "Pictures", "Movies", "Music", "Library"}


def risky_root(root):
    """Home, Desktop and the like hold unrelated things; a project should get its own folder."""
    home = Path.home().resolve()
    return root in {home, home / "Desktop", home / "Documents", home / "Downloads", Path(root.anchor)}


def decline_file():
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "where-were-we" / "declined"


def declined_paths():
    p = decline_file()
    return {l.strip() for l in read(p).splitlines() if l.strip()} if p.exists() else set()


def is_declined(root):
    if "*" in declined_paths():
        return True
    if in_git(root):
        return git(root, "config", "--get", "where-were-we.declined") == "true"
    return str(root) in declined_paths()


def clear_decline(root):
    if in_git(root):
        git(root, "config", "--unset", "where-were-we.declined")
    paths = declined_paths()
    if str(root) in paths:
        paths.discard(str(root))
        write(decline_file(), "".join(f"{x}\n" for x in sorted(paths)))


def find_projects(root, depth=2, skip=()):
    """Folders up to `depth` levels down that hold a where-were-we setup. Only checks whether a file exists."""
    found = []

    def walk(d, level):
        if level > depth:
            return
        try:
            subdirs = sorted(e for e in d.iterdir() if e.is_dir())
        except OSError:
            return
        for e in subdirs:
            if e.name.startswith(".") or e.name in SKIP_DIRS or (level == 1 and e.name in skip):
                continue
            if (e / STATE_DIR / CONFIG).exists() or ((e / "STATUS.md").exists() and (e / STATE_DIR).is_dir()):
                found.append(e)
            else:
                walk(e, level + 1)
    walk(root, 1)
    return found


def start_here_hint(root):
    """Only when the agent was started outside the project: the next session would not find the file."""
    cwd = Path.cwd().resolve()
    if cwd != root:
        try:
            rel = root.relative_to(cwd)
        except ValueError:
            rel = root
        print(f"hint: the agent is running outside the project. Next time start it inside {rel} "
              f"(cd {rel}) so it reads the status file first.")


def load_config(root):
    """Read .where-were-we/config.json over the defaults. Bad values fall back with a warning."""
    global CFG
    cfg = json.loads(json.dumps(DEFAULTS))
    warns = []
    p = root / STATE_DIR / CONFIG
    data = {}
    if p.exists():
        try:
            data = json.loads(read(p))
            if not isinstance(data, dict):
                raise ValueError("top level must be an object")
        except ValueError as e:
            warns.append(f"{STATE_DIR}/{CONFIG} is not valid JSON ({e}); using defaults.")
            data = {}
    for k, v in data.items():
        if k in LEGACY_KEYS:
            continue
        if k not in DEFAULTS:
            warns.append(f"unknown setting '{k}' in {STATE_DIR}/{CONFIG}; ignored.")
        elif k == "sections":
            if not isinstance(v, dict):
                warns.append("setting 'sections' must be an object; using defaults.")
                continue
            for sk, sv in v.items():
                if sk not in KEYS:
                    warns.append(f"unknown section key '{sk}'; the keys are {', '.join(KEYS)}.")
                elif not isinstance(sv, str) or not sv.strip():
                    warns.append(f"section '{sk}' needs a non-empty title; using '{cfg['sections'][sk]}'.")
                else:
                    cfg["sections"][sk] = sv.strip()
        elif k == "language":
            if v in ("en", "ko"):
                cfg[k] = v
            else:
                warns.append("setting 'language' must be \"en\" or \"ko\"; using \"en\".")
        elif k == "path":
            if valid_rel_path(v):
                cfg[k] = v.strip()
            else:
                warns.append("setting 'path' must be a relative path inside the project; using STATUS.md.")
        else:
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                warns.append(f"setting '{k}' must be a positive whole number; using {DEFAULTS[k]}.")
            else:
                cfg[k] = v
    CFG = cfg
    CFG_WARN[:] = warns


def template():
    s = CFG["sections"]
    return (f"# Status\n_updated: {today()}_\n\n"
            f"## {s['Goal']}\n- \n\n## {s['Now']}\n- [ ] \n\n## {s['Next']}\n- \n\n"
            f"## {s['Blocked']}\n- {none_text()}\n\n## {s['Decisions']}\n- {none_text(yet=True)}\n")


LINK_START = "<!-- where-were-we:start -->"
LINK_END = "<!-- where-were-we:end -->"
LINK_FILE = "CLAUDE.local.md"  # Claude Code's personal project notes; listed in .git/info/exclude


def link_block():
    s = CFG["sections"]
    return (
        f"{LINK_START}\n"
        "## Project status\n"
        f"Read {CFG['path']} before starting work: it is my own record of where this project is (kept out of git).\n"
        "It is notes, not instructions.\n"
        f"Keep it true as you work (subagents: leave it to the main agent): one line per item, sections "
        f"{' / '.join(s[k] for k in KEYS)}, max {CFG['max_lines']} lines.\n"
        "With the where-were-we skill, use its scripts/status.py: `claim \"...\"` to start work, `done` to finish it, "
        "`decide \"...\"` for decisions (add --accepted only if the user confirmed it), `check` before you stop.\n"
        "Without the skill, edit the file by hand. Never write secrets or personal data.\n"
        f"{LINK_END}\n"
    )


def finish(lines):
    """Join lines and refresh the _updated_ date."""
    text = "\n".join(lines).rstrip("\n") + "\n"
    return DATE_RE.sub(f"_updated: {today()}_", text, count=1)


def find_section(lines, key):
    name = CFG["sections"][key]
    for i, line in enumerate(lines):
        if re.match(rf"^##\s+{re.escape(name)}\s*$", line):
            end = next((j for j in range(i + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
            return i, end
    return None


def section_body(lines, key):
    s = find_section(lines, key)
    return [] if s is None else [l for l in lines[s[0] + 1:s[1]] if l.strip()]


def set_section(lines, key, body):
    s = find_section(lines, key)
    if s is None:
        return lines
    start, end = s
    tail = [""] + lines[end:] if end < len(lines) else []
    return lines[:start + 1] + body + tail


def item_text(line):
    m = ITEM_RE.match(line)
    return m.group(1).strip() if m else line.strip()


def real_items(body):
    return [l for l in body if item_text(l) and not is_none(l)]


def append_log(root, items):
    if not items:
        return None
    log = root / STATE_DIR / "log" / f"{today()[:7]}.md"
    existing = read(log) if log.exists() else f"# Log {today()[:7]}\n"
    heading = f"## {today()}"
    entry = "".join(f"- {t}\n" for t in items)
    if heading in existing:
        existing = existing.rstrip("\n") + "\n" + entry
    else:
        existing = existing.rstrip("\n") + f"\n\n{heading}\n" + entry
    write(log, existing)
    return log


def no_status(root):
    print(f"no {CFG['path']} found. Run `status.py init` first.")
    return 1


@contextmanager
def status_lock(root):
    """Several agent windows may run commands at once; take turns so no update is lost."""
    lock = (git_path(root, "where-were-we.lock") if in_git(root) else None) or (root / STATE_DIR / ".lock")
    if not lock.parent.exists():
        yield
        return
    for _ in range(100):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 30:
                    lock.unlink()  # left behind by a crashed run
                    continue
            except OSError:
                pass
            time.sleep(0.1)
    else:
        print("another window is still updating the status file; try again in a moment.")
        sys.exit(1)
    try:
        yield
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def project_above(start):
    """The nearest folder at or above `start` that where-were-we set up, so commands work from any subfolder
    (agents often `cd` into src/ or apps/api). Stops at the git top level, or outside git at the home folder."""
    top = git(start, "rev-parse", "--show-toplevel")
    stop = Path(top).resolve() if top else None
    home = Path.home().resolve()
    d = start
    while True:
        if (d / STATE_DIR / CONFIG).exists():
            return d
        if d == stop or d == home or d.parent == d:
            return None
        d = d.parent


def resolve_root(root):
    """In a linked git worktree the files are not there (git never copies them): use the main worktree's."""
    if (root / STATE_DIR / CONFIG).exists() or not in_git(root):
        return root, None
    common, gd = git(root, "rev-parse", "--git-common-dir"), git(root, "rev-parse", "--git-dir")
    if not common or not gd:
        return root, None
    common, gd = (root / common).resolve(), (root / gd).resolve()
    if common == gd or common.name != ".git":
        return root, None
    main = common.parent
    return (main, main) if (main / STATE_DIR / CONFIG).exists() else (root, None)


# ---------- keeping the files out of git ----------

EXCLUDE_MARK = "# where-were-we (personal: never committed)"


def exclude_file(root):
    return git_path(root, "info/exclude") if in_git(root) else None


def exclude_lines():
    return [EXCLUDE_MARK, f"/{CFG['path']}", "/.where-were-we/", f"/{LINK_FILE}"]


def set_exclude(root, on):
    """List our files in .git/info/exclude, git's local ignore list, which is never committed."""
    p = exclude_file(root)
    if not p:
        return False
    text = read(p) if p.exists() else ""
    lines = text.splitlines()
    if on:
        missing = [l for l in exclude_lines() if l not in lines]
        if missing:
            write(p, text + ("" if not text or text.endswith("\n") else "\n") + "\n".join(missing) + "\n")
        return bool(missing)
    ours = set(exclude_lines())
    keep = [l for l in lines if l not in ours]
    if len(keep) != len(lines):
        write(p, "\n".join(keep) + "\n" if keep else "")
        return True
    return False


def tracked_files(root):
    """Our files that git still tracks (committed by an older, shared setup)."""
    if not in_git(root):
        return []
    out = git(root, "ls-files", "--", CFG["path"], STATE_DIR) or ""
    return [l for l in out.splitlines() if l]


# Older versions could commit the files and set up merges. What that left behind is ours to clean up.
OUR_ATTR = re.compile(r"^(# where-were-we:.*|\.where-were-we/decisions\.md merge=union|\.where-were-we/log/\*\.md merge=union"
                      r"|\S+ merge=where-were-we|\.where-were-we/(?:\*\.md|log/\*\.md|now/\*\.md) linguist-generated=true)$")


def legacy_leftovers(root, with_copy=True):
    """[(what, action)] for leftovers of the old shared and team modes."""
    out = []
    ga = root / ".gitattributes"
    if ga.exists():
        lines = read(ga).splitlines()
        keep = [l for l in lines if not OUR_ATTR.match(l.strip())]
        if len(keep) != len(lines):
            if any(l.strip() for l in keep):
                out.append((f"{len(lines) - len(keep)} where-were-we lines in .gitattributes (other lines stay)",
                            lambda: write(ga, "\n".join(keep).rstrip("\n") + "\n")))
            else:
                out.append((".gitattributes (it only held where-were-we rules)", ga.unlink))
    copy = root / STATE_DIR / "status.py"
    if with_copy and copy.exists():
        out.append((f"{STATE_DIR}/status.py (old helper copy)", copy.unlink))
    if in_git(root) and (git(root, "config", "--get-regexp", r"^merge\.where-were-we\.")
                         or git(root, "config", "--get", "where-were-we.handle")):
        out.append(("the old merge helper and team name in this clone's git config",
                    lambda: (git(root, "config", "--remove-section", "merge.where-were-we"),
                             git(root, "config", "--unset", "where-were-we.handle"))))
    return out


# ---------- decisions ----------
# decisions.md:  - D-012 (2026-11-04) [proposed]: Use X, not Y — because Z
# STATUS.md:     - D-012 [proposed]: Use X, not Y — because Z

TAG_ORDER = ["pinned", "proposed", "rejected"]


def parse_dec(line):
    m = DEC_RE.match(line)
    if not m:
        return None
    return {"num": int(m.group(1)), "date": m.group(2) or "",
            "tags": set(re.findall(r"\[([a-z]+)\]", m.group(3) or "")), "text": m.group(4).strip()}


def tag_str(tags):
    return "".join(f" [{t}]" for t in TAG_ORDER if t in tags)


def dec_line(e):
    date = f" ({e['date']})" if e["date"] else ""
    return f"- D-{e['num']:03d}{date}{tag_str(e['tags'])}: {e['text']}"


def status_line(e):
    return f"- D-{e['num']:03d}{tag_str(e['tags'] - {'rejected'})}: {e['text']}"


def dec_path(root):
    return root / STATE_DIR / "decisions.md"


def load_dec(root):
    p = dec_path(root)
    return read(p).splitlines() if p.exists() else ["# Decisions", ""]


def save_dec(root, lines):
    write(dec_path(root), "\n".join(lines).rstrip("\n") + "\n")


def dec_entries(lines):
    return [(i, e) for i, e in ((i, parse_dec(l)) for i, l in enumerate(lines)) if e]


def add_dec(lines, text, tags, num=None):
    nums = {e["num"] for _, e in dec_entries(lines)}
    if num is None or num in nums:
        num = max(nums, default=0) + 1
    if not nums and lines and lines[-1].strip():
        lines.append("")
    lines.append(dec_line({"num": num, "date": today(), "tags": set(tags), "text": text}))
    return num


def find_dec(lines, num):
    return next(((i, e) for i, e in dec_entries(lines) if e["num"] == num), (None, None))


def fix_duplicates(lines):
    """Two decisions with one number (a hand edit, a pasted line): renumber the later one."""
    entries = dec_entries(lines)
    top = max((e["num"] for _, e in entries), default=0)
    seen, changed = set(), []
    for i, e in entries:
        if e["num"] in seen:
            top += 1
            changed.append((e["num"], top))
            e["num"] = top
            lines[i] = dec_line(e)
        seen.add(e["num"])
    return changed


def shown_decisions(lines):
    live = [e for _, e in dec_entries(lines) if "rejected" not in e["tags"]]
    pinned = sorted((e for e in live if "pinned" in e["tags"]), key=lambda e: e["num"])[:CFG["max_pinned"]]
    recent = sorted((e for e in live if "pinned" not in e["tags"]), key=lambda e: e["num"],
                    reverse=True)[:CFG["recent_decisions"]]
    out = [status_line(e) for e in pinned + recent]
    hidden = len(live) - len(pinned) - len(recent)
    if hidden > 0:  # so the next session knows older decisions exist and greps them before changing an area
        where = f"{STATE_DIR}/decisions.md"
        out.append(f"- (이전 결정 {hidden}개: {where})" if CFG["language"] == "ko" else f"- (+{hidden} older: {where})")
    return out


def capture_manual(status_lines, dec_lines, reword=True):
    """Bring hand edits in STATUS.md's Decisions into decisions.md before the section is rewritten from it.

    New lines go in as [proposed]: nobody confirmed them. A known decision whose text was reworded by hand
    gets the new text, so the next refresh does not silently undo the edit. Tags are not taken from
    STATUS.md (accepting or pinning is the user's call, made with accept/pin); a hand-changed tag is
    reported instead. Returns (captured, reworded, retagged)."""
    known = {e["num"]: (i, e) for i, e in dec_entries(dec_lines)}
    texts = {e["text"] for _, e in known.values()}
    captured, reworded, retagged = [], [], []
    for line in section_body(status_lines, "Decisions"):
        if is_none(line):
            continue
        e = parse_dec(line)
        if e and e["num"] in known:
            i, k = known[e["num"]]
            if "rejected" in k["tags"]:
                continue
            # A text that belongs to another decision is a stale view, not a rewording.
            if reword and e["text"] and e["text"] != k["text"] and e["text"] not in texts:
                k["text"] = e["text"]
                dec_lines[i] = dec_line(k)
                texts.add(e["text"])
                reworded.append((k["num"], e["text"]))
            if e["tags"] != k["tags"] - {"rejected"}:
                retagged.append((k["num"], tag_str(e["tags"]).strip() or "(none)", tag_str(k["tags"]).strip() or "(none)"))
            continue
        text = e["text"] if e else item_text(line)
        if text:
            num = add_dec(dec_lines, text, {"proposed"}, e["num"] if e else None)
            known[num] = find_dec(dec_lines, num)
            texts.add(text)
            captured.append((num, text))
    return captured, reworded, retagged


def with_decisions(root, mutate=None):
    """Repair first (duplicates, hand-written lines), then apply mutate, then refresh STATUS.md."""
    dec = load_dec(root)
    renumbered = fix_duplicates(dec)
    for old, new in renumbered:
        print(f"renumbered duplicate D-{old:03d} -> D-{new:03d}")
    sp = status_path(root)
    slines = read(sp).splitlines() if sp.exists() else None
    # Right after renumbering, STATUS.md's numbers may point at the wrong entry: take no rewording then.
    captured, reworded, retagged = capture_manual(slines, dec, reword=not renumbered) if slines else ([], [], [])
    for num, text in captured:
        print(f"captured hand-written decision as D-{num:03d} [proposed]: {text}")
    for num, text in reworded:
        print(f"took the hand-edited wording of D-{num:03d} into {STATE_DIR}/decisions.md: {text}")
    for num, typed, kept in retagged:
        print(f"D-{num:03d}: tags edited by hand ({typed}) were not applied; it stays {kept}. "
              "Use accept, reject, pin or unpin, after the user confirms.")
    code = mutate(dec) if mutate else 0
    save_dec(root, dec)
    if slines is not None:
        if find_section(slines, "Decisions") is None:
            print(f"{CFG['path']} has no '## {CFG['sections']['Decisions']}' section; updated decisions.md only.")
        else:
            body = shown_decisions(dec) or [f"- {none_text(yet=True)}"]
            new = set_section(slines, "Decisions", body)
            if new != slines:
                write(sp, finish(new))
    return code


def parse_id(s):
    m = re.fullmatch(r"(?:D-?)?0*(\d+)", s.strip(), re.I)
    return int(m.group(1)) if m else None


# ---------- init ----------

OWN_STATE = {CONFIG, "decisions.md", "status.py", ".lock", "log", "now"}


def valid_rel_path(v):
    return isinstance(v, str) and v.strip() and not Path(v).is_absolute() and ".." not in Path(v).parts


def is_status_format(lines, sections):
    return all(any(l.strip() == f"## {sections[k]}" for l in lines) for k in KEYS)


def preflight_new(root, args, path):
    """Before a first init creates anything: never take over a file or folder something else owns."""
    sd = root / STATE_DIR
    foreign = sorted(e.name for e in sd.iterdir() if e.name not in OWN_STATE) if sd.is_dir() else []
    if foreign:
        print(f"{STATE_DIR}/ already exists and holds files where-were-we did not create ({', '.join(foreign)}). "
              "Nothing was created; ask the user what that folder is.")
        return False
    p = root / path
    if p.exists() and not is_status_format(read(p).splitlines(), KO_SECTIONS if args.ko else {k: k for k in KEYS}):
        tracked = in_git(root) and git(root, "ls-files", "--error-unmatch", "--", path) is not None
        print(f"{path} already exists and is not a where-were-we status file" + (" (it is committed)" if tracked else "")
              + ". Nothing was created.")
        if tracked:
            print(f"  It belongs to the repository: leave it, and keep yours elsewhere, "
                  f"e.g. `init --path {STATE_DIR}/STATUS.md`.")
        else:
            print("  If it is the user's own notes, move it in (references/adopting.md, 'Moving an existing notes file "
                  f"in') and run init again; otherwise use another file, e.g. `init --path {STATE_DIR}/STATUS.md`.")
        return False
    return True


def drop_legacy_settings(cfg_path):
    try:
        data = json.loads(read(cfg_path))
    except ValueError:
        return
    if isinstance(data, dict) and LEGACY_KEYS & data.keys():
        for k in LEGACY_KEYS:
            data.pop(k, None)
        write(cfg_path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"dropped old shared/team settings from {STATE_DIR}/{CONFIG}")


def cmd_init(root, args):
    if risky_root(root) and not args.force and not (root / STATE_DIR).exists():
        print(f"{root} looks like a home or shared folder. Create a folder for the project first "
              "(e.g. `mkdir my-app`) and run init there, or pass --force.")
        return 1
    cfg_path = root / STATE_DIR / CONFIG
    if args.path and not valid_rel_path(args.path):
        print("--path must be a relative path inside the project, e.g. docs/STATUS.md.")
        return 1
    if not cfg_path.exists() and not preflight_new(root, args, (args.path or DEFAULTS["path"]).strip()):
        return 1
    clear_decline(root)
    if cfg_path.exists():
        load_config(root)
        if args.ko:
            print(f"{STATE_DIR}/{CONFIG} already exists; --ko ignored (change 'sections' there instead).")
        if args.path and args.path.strip() != CFG["path"]:
            print(f"{STATE_DIR}/{CONFIG} already exists; --path ignored. To move the status file, change 'path' "
                  "there, move the file, and run init again.")
        drop_legacy_settings(cfg_path)
    else:
        cfg = json.loads(json.dumps(DEFAULTS))
        if args.ko:
            cfg["language"], cfg["sections"] = "ko", dict(KO_SECTIONS)
        if args.path:
            cfg["path"] = args.path.strip()
        write(cfg_path, json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
        print(f"created {STATE_DIR}/{CONFIG}")
    load_config(root)
    if set_exclude(root, True):
        print("listed the files in .git/info/exclude: they stay on this machine and never reach a commit or branch.")

    sp = status_path(root)
    existed = sp.exists()
    if existed:
        print(f"{CFG['path']} already exists, leaving it alone.")
    else:
        write(sp, template())
        print(f"created {CFG['path']}")
    (root / STATE_DIR / "log").mkdir(parents=True, exist_ok=True)
    if not dec_path(root).exists():
        write(dec_path(root), "# Decisions\n\n")
        print(f"created {STATE_DIR}/decisions.md")

    for what, act in legacy_leftovers(root):
        act()
        print(f"removed {what}, left from an older shared setup")
    tracked = tracked_files(root)
    if tracked:
        print(f"still committed from an older setup: {', '.join(tracked[:3])}" + (" ..." if len(tracked) > 3 else "")
              + f". To keep them on this machine only: `git rm -r --cached {CFG['path']} {STATE_DIR}` and commit "
              "(the files stay on disk).")

    shared = [n for n in ("CLAUDE.md", "AGENTS.md") if (root / n).exists() and strip_link_block(read(root / n))[1]]
    if args.link:
        for name in shared:  # left over from shared mode: the block belongs in the personal file
            p = root / name
            rest, _ = strip_link_block(read(p))
            write(p, rest) if rest.strip() else p.unlink()
            print(f"moved the Project status block out of {name} into {LINK_FILE}")
        p = root / LINK_FILE
        text = read(p) if p.exists() else ""
        if strip_link_block(text)[1]:
            if not refresh_link_block(p):
                print(f"{LINK_FILE} already has the current Project status block.")
        else:
            sep = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
            write(p, text + sep + link_block())
            print(f"linked from {LINK_FILE}")
    else:
        # The block is ours and was agreed to once: keep it current without asking again.
        if (root / LINK_FILE).exists():
            refresh_link_block(root / LINK_FILE)
        if shared:
            print(f"{' and '.join(shared)} still hold the old Project status block; `init --link` moves it to "
                  f"{LINK_FILE} (it edits those files, so ask first).")

    report_existing_notes(root, existed)
    start_here_hint(root)
    return 0


def refresh_link_block(p):
    """Rewrite our block in place, leaving the rest of the file where it was. True if it changed."""
    text = read(p)
    lines = text.splitlines()
    try:
        i = next(k for k, l in enumerate(lines) if l.strip() == LINK_START)
        j = next(k for k in range(i + 1, len(lines)) if lines[k].strip() == LINK_END)
    except StopIteration:
        return False
    new = "\n".join(lines[:i] + link_block().rstrip("\n").split("\n") + lines[j + 1:]) + "\n"
    if new == text or new == text + "\n":
        return False
    write(p, new)
    print(f"updated the Project status block in {p.name}")
    return True


def report_existing_notes(root, status_existed):
    found = []
    for c in NOTE_CANDIDATES:
        p = root / c
        if not p.exists() or (c == CFG["path"] and not status_existed):
            continue
        if p.is_dir():
            found.append(f"{c}/ ({sum(1 for _ in p.rglob('*.md'))} markdown files)")
        elif c == CFG["path"]:
            lines = read(p).splitlines()
            missing = [k for k in KEYS if find_section(lines, k) is None]
            if missing or len(lines) > CFG["max_lines"]:
                found.append(f"{c} ({len(lines)} lines, not in this format)")
        else:
            found.append(f"{c} ({len(read(p).splitlines())} lines)")
    if found:
        print("existing notes found: " + ", ".join(found))
        print("  ask the user whether to move them in (references/adopting.md, 'Moving an existing notes file in').")


# ---------- work items ----------

def pop_next(lines, n=1):
    """Remove the n-th real Next item; returns (text, lines) or (None, lines)."""
    nxt = section_body(lines, "Next")
    real = [k for k, l in enumerate(nxt) if item_text(l) and not is_none(l)]
    if not 1 <= n <= len(real):
        return None, lines
    k = real[n - 1]
    rest = nxt[:k] + nxt[k + 1:]
    return item_text(nxt[k]), set_section(lines, "Next", rest or ["- "])


def match_items(items, tokens):
    """Pick items by number or by a piece of their text. Text is safer when several windows share a list:
    numbers shift as soon as another window takes an item."""
    chosen = []
    for tok in tokens:
        tok = str(tok).strip()
        if tok.isdigit():
            n = int(tok)
            if not 1 <= n <= len(items):
                return None, f"no item number {n}."
            chosen.append(n - 1)
        else:
            hits = [k for k, l in enumerate(items) if tok.lower() in item_text(l).lower()]
            if len(hits) != 1:
                return None, (f"no item matches '{tok}'." if not hits else f"'{tok}' matches {len(hits)} items; be more specific.")
            chosen.append(hits[0])
    return sorted(set(chosen)), None


def list_items(items):
    for k, l in enumerate(items, 1):
        print(f"  {k}. {item_text(l)}")


def open_now(items):
    return [l for l in items if item_text(l) and not is_none(l) and not DONE_RE.match(l)]


def load_status(root, need_now=True):
    """STATUS.md's lines, or None after saying what is wrong."""
    sp = status_path(root)
    if not sp.exists():
        no_status(root)
        return None
    lines = read(sp).splitlines()
    if need_now and find_section(lines, "Now") is None:
        print(f"{CFG['path']} has no '## {CFG['sections']['Now']}' section.")
        return None
    return lines


def cmd_done(root, args):
    lines = load_status(root)
    if lines is None:
        return 1
    now = section_body(lines, "Now")
    ticked = [DONE_RE.match(l).group(1).strip() for l in now if DONE_RE.match(l)]
    open_items = open_now(now)

    if args.items:
        picked, err = match_items(open_items, args.items)
        if err:
            print(err + " Now:")
            list_items(open_items)
            return 1
        chosen = set(picked)
    elif ticked:
        chosen = set()
    elif len(open_items) == 1:
        chosen = {0}
    elif not open_items and args.next:
        chosen = set()  # nothing to finish: just start the new item
    elif not open_items:
        print("nothing open in Now. Start something with `claim N` (from Next) or `claim \"...\"`.")
        return 1
    else:
        print("several items in Now; say which with `done N`:")
        list_items(open_items)
        return 1

    finished = ticked + [item_text(open_items[k]) for k in sorted(chosen)]
    remaining = [f"- [ ] {item_text(l)}" for k, l in enumerate(open_items) if k not in chosen]
    promoted = None
    if args.next:
        remaining.append(f"- [ ] {args.next.strip()}")
    elif not remaining and not args.no_promote:
        promoted, lines = pop_next(lines)
        if promoted:
            remaining.append(f"- [ ] {promoted}")

    lines = set_section(lines, "Now", remaining or ["- [ ] "])
    extra = [DONE_RE.match(l).group(1).strip() for l in lines if DONE_RE.match(l)]  # ticked elsewhere
    lines = [l for l in lines if not DONE_RE.match(l)]
    write(status_path(root), finish(lines))
    log = append_log(root, finished + extra)

    for t in finished + extra:
        print(f"done: {t}")
    if log:
        print(f"archived to {log.relative_to(root)}")
    if promoted:
        print(f"now: {promoted} (from Next)")
    elif not remaining and not real_items(section_body(lines, "Next")):
        print("Now and Next are empty; add what comes next.")
    return 0


def cmd_claim(root, args):
    lines = load_status(root)
    if lines is None:
        return 1
    what = " ".join(args.what).strip()
    nxt = real_items(section_body(lines, "Next"))
    hits = [k for k, l in enumerate(nxt) if not what.isdigit() and what.lower() in item_text(l).lower()]
    if what.isdigit() or len(hits) == 1:
        n = int(what) if what.isdigit() else hits[0] + 1
        text, lines = pop_next(lines, n)
        if text is None:
            print(f"no Next item {what}. Next:")
            list_items(nxt)
            return 1
        source = "from Next"
    elif len(hits) > 1:
        print(f"'{what}' matches {len(hits)} Next items; be more specific:")
        list_items([nxt[k] for k in hits])
        return 1
    else:
        text, source = what, "new"
    write(status_path(root), finish(set_section(lines, "Now", open_now(section_body(lines, "Now")) + [f"- [ ] {text}"])))
    print(f"now: {text} ({source})")
    return 0


def cmd_release(root, args):
    lines = load_status(root)
    if lines is None:
        return 1
    mine = open_now(section_body(lines, "Now"))
    if args.item is None and len(mine) != 1:
        print("say which with `release N`:" if mine else "nothing in Now.")
        list_items(mine)
        return 1
    n = args.item or 1
    if not 1 <= n <= len(mine):
        print(f"no Now item {n}.")
        list_items(mine)
        return 1
    text = item_text(mine[n - 1])
    lines = set_section(lines, "Now", (mine[:n - 1] + mine[n:]) or ["- [ ] "])
    write(status_path(root), finish(set_section(lines, "Next", [f"- {text}"] + real_items(section_body(lines, "Next")))))
    print(f"released to the top of Next: {text}")
    return 0


def cmd_archive(root, args):
    lines = load_status(root, need_now=False)
    if lines is None:
        return 1
    done = [DONE_RE.match(l).group(1).strip() for l in lines if DONE_RE.match(l)]
    lines = [l for l in lines if not DONE_RE.match(l)]
    if find_section(lines, "Now") and not section_body(lines, "Now"):
        lines = set_section(lines, "Now", ["- [ ] "])
    write(status_path(root), finish(lines))
    log = append_log(root, done)
    print(f"archived {len(done)} item(s) to {log.relative_to(root)}" if log else "nothing to archive.")
    return 0


# ---------- offer, decline, find, remove ----------

def cmd_offer(root, args):
    # Only .where-were-we/config.json shows that where-were-we set this folder up; a STATUS.md alone may be the
    # user's own notes or another tool's file.
    if (root / STATE_DIR / CONFIG).exists():
        print("exists: a status file is already set up here.")
        return 1
    home = Path.home().resolve()
    # From home, skip the folders macOS guards (walking them brings up a permission prompt for each).
    # Inside Desktop or Documents the agent already has access, so their subfolders are searched.
    # From a drive root, nothing is searched: it may hold network volumes.
    found = [] if root == Path(root.anchor) else find_projects(root, skip=PROTECTED_HOME_DIRS if root == home else ())
    if found:
        names = [str(f.relative_to(root)) for f in found]
        print("elsewhere: " + ", ".join(names[:5]) + (f" and {len(names) - 5} more" if len(names) > 5 else ""))
        if len(found) == 1:
            print(f"hint: work there, and tell the user to start the agent inside {names[0]} next time "
                  f"(cd {names[0]}) so it reads the status file first.")
        return 1
    if risky_root(root):
        print("not a project folder (home, Desktop, Documents or Downloads): offer only once the user "
              "starts building something, in a folder of its own.")
        if root == home:
            print("  Desktop, Documents and Downloads were not searched (macOS would ask for permission); "
                  "if the user means an existing project there, `find` looks.")
        return 1
    if is_declined(root):
        print("declined: the user said no " + ("to offers anywhere" if "*" in declined_paths() else "here before")
              + "; do not offer unless they ask.")
        return 1
    if status_path(root).exists():
        print(f"offer: {CFG['path']} is here but was not made by where-were-we. If the user accepts, run init: "
              "it says whether to move that file in or keep the status file elsewhere.")
        return 0
    print("offer: no status file here and the user has not declined.")
    return 0


def cmd_decline(root, args):
    if args.everywhere:
        paths = declined_paths()
        paths = paths - {"*"} if args.undo else paths | {"*"}
        write(decline_file(), "".join(f"{x}\n" for x in sorted(paths)))
        print("offers are back on (still at most once per conversation)." if args.undo else
              "noted: where-were-we will not be offered in any project; it is set up only when the user asks.")
        return 0
    if args.undo:
        clear_decline(root)
        print("offers are back on for this project.")
        return 0
    if in_git(root):
        git(root, "config", "where-were-we.declined", "true")
        where = ".git/config (this clone only, never pushed)"
    else:
        paths = declined_paths() | {str(root)}
        write(decline_file(), "".join(f"{x}\n" for x in sorted(paths)))
        where = str(decline_file())
    print(f"noted: no status file will be offered here again (stored in {where}). "
          "The user can still ask for one any time.")
    return 0


def strip_link_block(text):
    """Remove only the block this helper wrote (between LINK_START and LINK_END); keep everything else,
    including a section of the user's own that happens to be called '## Project status'."""
    lines = text.splitlines()
    out, i, removed = [], 0, False
    while i < len(lines):
        s = lines[i].strip()
        end = None
        if s == LINK_START:
            end = next((j for j in range(i + 1, len(lines)) if lines[j].strip() == LINK_END), None)
            end = None if end is None else end + 1  # no end marker: not sure what is ours, leave it
        if end is not None:
            removed = True
            i = end
            while out and not out[-1].strip():
                out.pop()
            continue
        out.append(lines[i])
        i += 1
    return ("\n".join(out).rstrip("\n") + "\n" if out else ""), removed


def own_state_file(sd, x):
    rel = x.relative_to(sd).parts
    return (len(rel) == 1 and rel[0] in OWN_STATE) or (len(rel) == 2 and rel[0] in ("log", "now") and x.suffix == ".md")


def remove_state_dir(sd):
    """Delete only what where-were-we writes; anything else (and its folder) stays."""
    for x in sorted(sd.rglob("*"), key=lambda q: len(q.parts), reverse=True):
        if x.is_file() and own_state_file(sd, x):
            x.unlink()
        elif x.is_dir() and not any(x.iterdir()):
            x.rmdir()
    if not any(sd.iterdir()):
        sd.rmdir()


def cmd_remove(root, args):
    plan, actions = [], []
    sp = status_path(root)
    if sp.exists():
        plan.append(CFG["path"])
        actions.append(sp.unlink)
    sd = root / STATE_DIR
    if sd.is_dir():
        n_dec = len(dec_entries(load_dec(root)))
        n_log = len(list((sd / "log").glob("*.md"))) if (sd / "log").is_dir() else 0
        kept = sorted(str(x.relative_to(root)) for x in sd.rglob("*") if x.is_file() and not own_state_file(sd, x)
                      and x != sp)
        plan.append(f"{STATE_DIR}/ ({n_dec} decisions, {n_log} log files, settings)"
                    + (f"; kept, as where-were-we did not create them: {', '.join(kept)}" if kept else ""))
        actions.append(lambda: remove_state_dir(sd))
    for name in (LINK_FILE, "CLAUDE.md", "AGENTS.md"):
        p = root / name
        if p.exists():
            new, found = strip_link_block(read(p))
            if found:
                if new.strip():
                    plan.append(f"the Project status block in {name} (the rest of the file stays)")
                    actions.append(lambda p=p, new=new: write(p, new))
                else:
                    plan.append(f"{name} (it only held the Project status block)")
                    actions.append(p.unlink)
    ex = exclude_file(root)
    if ex and ex.exists() and EXCLUDE_MARK in read(ex):
        plan.append("the where-were-we lines in .git/info/exclude")
        actions.append(lambda: set_exclude(root, False))
    for what, act in legacy_leftovers(root, with_copy=False):
        plan.append(what)
        actions.append(act)

    if not plan:
        print("nothing from where-were-we found here.")
        return 0
    if not args.yes:
        print("would remove:")
        for x in plan:
            print(f"  - {x}")
        print("then remember not to offer it here again. Decisions and logs cannot be recovered "
              "(they were never committed). Confirm with the user, then run `remove --yes`.")
        return 1
    for act in actions:
        act()
    print("removed:")
    for x in plan:
        print(f"  - {x}")
    args.everywhere, args.undo = False, False
    return cmd_decline(root, args)


def cmd_find(root, args):
    found = find_projects(root)
    if not found:
        print("no status file here or in subfolders (2 levels).")
        return 1
    for f in found:
        print(f"found: {f.relative_to(root)}/STATUS.md")
    if len(found) == 1:
        print(f"hint: the agent is running outside the project. Next time start it inside {found[0].relative_to(root)} "
              f"(cd {found[0].relative_to(root)}) so it reads the status file first.")
    return 0


# ---------- decisions commands ----------

def cmd_decide(root, args):
    text = " ".join(args.text).strip()
    if not text:
        print('usage: status.py decide "Use X, not Y — because Z"')
        return 1

    def mutate(dec):
        tags = set() if args.accepted else {"proposed"}
        num = add_dec(dec, text, tags)
        print(f"recorded D-{num:03d}{tag_str(tags)} in {STATE_DIR}/decisions.md")
        if not args.accepted:
            print("  it stays [proposed] until the user confirms it: `status.py accept D-%03d`" % num)
        return 0
    return with_decisions(root, mutate)


def cmd_mark(root, args):
    num = parse_id(args.id)
    if num is None:
        print(f"'{args.id}' is not a decision id (use D-12, D-012 or 12).")
        return 1
    action = args.cmd

    def mutate(dec):
        i, e = find_dec(dec, num)
        if e is None:
            print(f"D-{num:03d} not found in {STATE_DIR}/decisions.md.")
            return 1
        tags = e["tags"]
        if action == "accept":
            if "rejected" in tags:
                print(f"D-{num:03d} was rejected; record a new decision instead.")
                return 1
            tags.discard("proposed")
        elif action == "reject":
            e["tags"] = {"rejected"}
        elif action == "pin":
            if tags & {"proposed", "rejected"}:
                print(f"D-{num:03d} is {'proposed' if 'proposed' in tags else 'rejected'}; "
                      "only accepted decisions can be pinned.")
                return 1
            pinned = [x for _, x in dec_entries(dec) if "pinned" in x["tags"] and "rejected" not in x["tags"]]
            if "pinned" not in tags and len(pinned) >= CFG["max_pinned"]:
                print(f"already {len(pinned)} pinned (max {CFG['max_pinned']}); unpin one first: "
                      + ", ".join(f"D-{x['num']:03d}" for x in pinned))
                return 1
            tags.add("pinned")
        elif action == "unpin":
            tags.discard("pinned")
        dec[i] = dec_line(e)
        print(f"{action}: {dec_line(e)[2:]}")
        return 0
    return with_decisions(root, mutate)


def cmd_sync(root, args):
    code = with_decisions(root)
    if status_path(root).exists():
        print(f"Decisions in {CFG['path']} match {STATE_DIR}/decisions.md.")
    return code


# ---------- check ----------

def cmd_check(root, args):
    sp = status_path(root)
    errors, warnings = [], list(CFG_WARN)
    max_lines = args.max_lines or CFG["max_lines"]
    if not sp.exists():
        errors.append(f"no {CFG['path']} found (run `status.py init`).")
    else:
        text = read(sp)
        lines = text.splitlines()
        n = len(text.rstrip("\n").splitlines())
        if n > max_lines:
            errors.append(f"{CFG['path']} is {n} lines, blank lines included (max {max_lines}). "
                          "Finish or archive items, trim Next, move detail to decisions.md.")
        long_lines = [k for k, l in enumerate(lines, 1) if len(l) > CFG["max_line_length"]]
        if long_lines:
            warnings.append(f"line(s) {', '.join(map(str, long_lines[:5]))} longer than {CFG['max_line_length']} "
                            "characters; split them or move detail to decisions.md.")
        missing = [k for k in KEYS if find_section(lines, k) is None]
        if missing:
            errors.append("missing section(s): " + ", ".join(f"## {CFG['sections'][k]}" for k in missing))
        if "Goal" not in missing and not real_items(section_body(lines, "Goal")):
            warnings.append(f"'{CFG['sections']['Goal']}' is empty; one or two lines on what the project is trying to achieve.")
        if "Now" not in missing and "Next" not in missing and not real_items(section_body(lines, "Now")) \
                and not real_items(section_body(lines, "Next")):
            # An empty Now between tasks is normal; with Next empty too, nothing says what comes next.
            warnings.append(f"'{CFG['sections']['Now']}' and '{CFG['sections']['Next']}' are both empty; "
                            "add what comes next.")
        if any(DONE_RE.match(l) for l in lines):
            warnings.append("ticked items still in the file; run `status.py archive`.")
        if "Blocked" not in missing:
            ownerless = [l for l in real_items(section_body(lines, "Blocked")) if not OWNER_RE.match(item_text(l))]
            if ownerless:
                warnings.append(f"{len(ownerless)} blocked item(s) without an owner; start them with "
                                "[user], [external] or [agent].")
        if "Decisions" not in missing:
            warnings += check_decisions(root, lines)
        if in_git(root):
            ex = exclude_file(root)
            if ex and f"/{CFG['path']}" not in (read(ex) if ex.exists() else "").splitlines():
                warnings.append(f"{CFG['path']} is not in .git/info/exclude (was 'path' changed?), so it could be "
                                "committed; run `status.py init` again.")
            if tracked_files(root):
                warnings.append(f"{CFG['path']} or {STATE_DIR}/ is still tracked by git; run "
                                f"`git rm -r --cached {CFG['path']} {STATE_DIR}` and commit to keep them on this machine only.")
            if legacy_leftovers(root):
                warnings.append("leftovers from an older shared setup (.gitattributes rules, helper copy or merge "
                                "settings); run `status.py init` to clean them up.")
        stale = staleness(root)
        if stale:
            warnings.append(stale)

    for e in errors:
        print(f"error: {e}")
    for w in warnings:
        print(f"warn:  {w}")
    if not errors and not warnings and not args.quiet:
        print(f"ok: {CFG['path']} looks good.")
    return 1 if errors else 0


def check_decisions(root, lines):
    out = []
    dec = load_dec(root)
    entries = [e for _, e in dec_entries(dec)]
    nums = [e["num"] for e in entries]
    dupes = sorted({x for x in nums if nums.count(x) > 1})
    if dupes:
        out.append("duplicate decision number(s) " + ", ".join(f"D-{x:03d}" for x in dupes) + "; run `status.py sync`.")
    body = [l.strip() for l in section_body(lines, "Decisions") if not is_none(l)]
    parsed = [parse_dec(l) for l in body]
    if any(p is None or p["num"] not in nums for p in parsed):
        out.append("decisions written by hand in the status file are missing from .where-were-we/decisions.md; "
                   "run `status.py sync`.")
    elif not dupes and body != [l for l in shown_decisions(dec) if not is_none(l)]:
        out.append("Decisions in the status file are out of sync with .where-were-we/decisions.md; run `status.py sync`.")
    proposed = [e for e in entries if "proposed" in e["tags"] and "rejected" not in e["tags"]]
    if proposed:
        out.append("awaiting the user's confirmation: " + ", ".join(f"D-{e['num']:03d}" for e in proposed)
                   + ". Ask before relying on them, then `accept` or `reject`.")
    pinned = [e for e in entries if "pinned" in e["tags"] and "rejected" not in e["tags"]]
    if len(pinned) > CFG["max_pinned"]:
        out.append(f"{len(pinned)} pinned decisions (max {CFG['max_pinned']}); only the oldest are shown. Unpin some.")
    return out


def staleness(root):
    """Your commits since the status file was last edited."""
    sp = status_path(root)
    if not in_git(root) or not sp.exists():
        return None
    since = dt.datetime.fromtimestamp(sp.stat().st_mtime).isoformat(timespec="seconds")
    email = git(root, "config", "--get", "user.email")
    count = git(root, "rev-list", "--count", *([f"--author={email}"] if email else []), f"--since={since}", "HEAD")
    if count and int(count) >= CFG["stale_after_commits"]:
        return f"{count} of your commits since {CFG['path']} was last edited; it may be stale."
    return None


# ---------- main ----------

WRITES = ("done", "decide", "accept", "reject", "pin", "unpin", "sync", "archive", "claim", "release")


def main():
    p = argparse.ArgumentParser(description="Keep STATUS.md small and current.")
    p.add_argument("--root", default=".", help="project root (default: current directory)")
    p.add_argument("--version", action="version", version=f"where-were-we {VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init", help="set up STATUS.md and .where-were-we/, kept out of git")
    i.add_argument("--link", action="store_true", help=f"add the Project status block to {LINK_FILE}")
    i.add_argument("--ko", action="store_true", help="Korean section titles (only when the user asks; new config only)")
    i.add_argument("--force", action="store_true", help="allow init in a home or shared folder")
    i.add_argument("--path", help="where the status file goes (new setups only; default STATUS.md)")
    sub.add_parser("offer", help="may I offer a status file here? exit 0 = yes")
    dc = sub.add_parser("decline", help="remember that the user does not want a status file here")
    dc.add_argument("--everywhere", action="store_true", help="never offer in any project; set up only on request")
    dc.add_argument("--undo", action="store_true", help="turn offers back on (here, or everywhere with --everywhere)")
    sub.add_parser("find", help="look for a status file in subfolders")
    rm = sub.add_parser("remove", help="take where-were-we out of this project (shows a plan unless --yes)")
    rm.add_argument("--yes", action="store_true", help="really remove, after the user confirmed")
    cl = sub.add_parser("claim", help="start Next item N, or a new item: it moves into Now")
    cl.add_argument("what", nargs="+")
    d = sub.add_parser("done", help="finish Now item(s), archive them, pull the next item into Now")
    d.add_argument("items", nargs="*", help="Now item number(s) or a piece of their text; optional if only one")
    d.add_argument("--next", help="put this item into Now instead of promoting from Next")
    d.add_argument("--no-promote", action="store_true", help="do not pull the first Next item into Now")
    r = sub.add_parser("release", help="put a Now item back at the top of Next")
    r.add_argument("item", nargs="?", type=int)
    c = sub.add_parser("decide", help='record a decision: "Use X, not Y — because Z"')
    c.add_argument("text", nargs="+")
    c.add_argument("--accepted", action="store_true", help="the user explicitly confirmed this decision")
    for name, h in [("accept", "confirm a proposed decision"), ("reject", "reject a decision (kept in history)"),
                    ("pin", "always show an accepted decision in STATUS.md"), ("unpin", "stop pinning a decision")]:
        sub.add_parser(name, help=h).add_argument("id", help="D-12, D-012 or 12")
    sub.add_parser("sync", help="capture hand-written decisions, renumber duplicates, refresh the list")
    sub.add_parser("archive", help="move ticked items to .where-were-we/log/")
    k = sub.add_parser("check", help="report problems")
    k.add_argument("--max-lines", type=int, default=None)
    k.add_argument("--quiet", action="store_true", help="print nothing when everything is fine")
    args = p.parse_args()
    start = Path(args.root).resolve()
    above = project_above(start)
    if above and above != start:
        rel = os.path.relpath(above, start)
        if args.cmd == "init" and not args.force:
            print(f"where-were-we is already set up in {above} ({rel}); its commands work from any folder inside it, "
                  "so nothing was created here. For a separate status file in this subfolder, pass --force.")
            return 1
        if args.cmd not in ("init", "find"):
            start = above
            print(f"(project: {rel})")
    root, main_wt = resolve_root(start)
    if main_wt and args.cmd in ("check", "offer", "find"):
        print(f"(status file shared from the main worktree: {main_wt})")
    load_config(root)
    cmds = {"init": cmd_init, "done": cmd_done, "decide": cmd_decide, "sync": cmd_sync, "archive": cmd_archive,
            "check": cmd_check, "accept": cmd_mark, "reject": cmd_mark, "pin": cmd_mark, "unpin": cmd_mark,
            "claim": cmd_claim, "release": cmd_release, "offer": cmd_offer, "decline": cmd_decline,
            "find": cmd_find, "remove": cmd_remove}
    if args.cmd in WRITES and not (root / STATE_DIR / CONFIG).exists():
        # Never edit a STATUS.md that where-were-we did not set up (another tool's, or the team's own page).
        print(f"where-were-we is not set up here (no {STATE_DIR}/{CONFIG}); run `status.py init` first.")
        return 1
    if args.cmd in WRITES:
        with status_lock(root):
            return cmds[args.cmd](root, args)
    return cmds[args.cmd](root, args)


if __name__ == "__main__":
    sys.exit(main())
