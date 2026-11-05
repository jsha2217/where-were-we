# Git, merges and settings

## Personal mode

`init` chooses personal mode when other people have commits in the repository (a company repo, a cloned tutorial) and neither `--shared` nor `--team` was given; `--personal` forces it. Then:

- `STATUS.md`, `.where-were-we/` and `CLAUDE.local.md` are listed in `.git/info/exclude`, git's local ignore list, which is never committed. Nothing shows up in `git status` or in a pull request.
- Because the files are untracked, they stay in place when the user switches branches (e.g. to a hotfix and back).
- No `.gitattributes` rules or merge helper are needed.
- `init --link` writes the Project status block to `CLAUDE.local.md`, a personal file Claude Code reads alongside CLAUDE.md. Other tools may not read it; then the skill relies on the user's own "where were we".
- Staleness is measured by the user's own commits since STATUS.md was last edited.
- Trade-off: the files are not backed up or shared through git, and do not follow the user to another clone.

To share later, after the team agrees: `init --shared` (or `--team`) removes the exclude lines and the CLAUDE.local.md block, adds the merge rules, and asks for `init --link` to update CLAUDE.md / AGENTS.md. `init --personal` goes the other way.

## Branches and merges

The status file describes the branch it is on and travels with it. `init` sets up `.gitattributes` so merges mostly resolve themselves:

- `.where-were-we/decisions.md` and the logs use `merge=union`: both sides' lines are kept.
- The status file uses `merge=where-were-we`, a section-aware merge in the helper: within each section, items either side removed are dropped and items either side added are kept, so two people taking different Next items, or adding different Blocked lines, merge cleanly. If both sides reworded the same line differently (two versions of the Goal, say), the helper keeps both between conflict markers and git reports a conflict, rather than silently keeping two goals; in Now, where each branch may simply have started something different, both are kept. `check` reports leftover markers. Never use `merge=union` for the status file; it would bring removed items back.

The where-were-we merge needs to be registered in each clone's git config. `init` and `whoami` do this only when run from the installed skill, and register the skill's `scripts/status.py` by absolute path, never the repository's `.where-were-we/status.py`: a merge helper inside the repository would run whatever was last committed on every `git pull`. Teammates without the skill get git's normal merge, which may show a conflict. If the registered script disappears (skill moved or updated), git's normal merge with conflict markers runs instead; `check` warns, and running `init` with the skill's script registers the new path. After any merge, run `sync` (two branches may have numbered a decision the same) and `check`. If a conflict does appear, keep the target branch's version, re-add what is still true from the other side, then `sync` and `check`.

## Parallel agents and worktrees

Several agent windows may update the status files at once; the helper takes turns with a lock and writes atomically, so nothing is lost. In shared mode each git worktree has its own copy, merged later like any branch (personal Now files too). In personal mode a linked worktree uses the main worktree's files automatically.

## CI and pull requests

`check --ci` runs only repository checks (format, length, secrets and personal data, decisions, merge rules) and skips per-machine warnings; it exits non-zero on errors, so it can gate a pipeline. In shared mode the record files (`.where-were-we/*.md`, `.where-were-we/log/*.md`, `.where-were-we/now/*.md`) are marked `linguist-generated`, so GitHub collapses them in pull-request diffs while STATUS.md and `.where-were-we/status.py` stay visible: changes to the helper script should always be reviewed. Run from the installed skill, `check` reports an error when the project's `.where-were-we/status.py` has the skill's version but different content (edited in the repository), and a warning when the versions differ; `init` with the skill's script restores it, and never replaces a newer copy with an older one. The CLAUDE.md / AGENTS.md block tells agents to use the skill's script when they have it, and the repository copy only otherwise. That leaves one path a hostile commit could use: a teammate without the skill whose agent runs the repository copy on the block's say-so, with nothing to compare it against. Treat changes to `.where-were-we/status.py` in a pull request like changes to any build script, and if a teammate's copy reports a newer version than your skill, find out who changed it before running it.

## Settings

`.where-were-we/config.json` is created by `init` and can be left alone. Keys: `path` (where the status file lives, e.g. `docs/STATUS.md`; for a new setup `init --path` sets it), `language` (`en` or `ko`), `team` (true/false), `personal` (true/false), `max_lines`, `max_line_length`, `stale_after_commits` (default 5), `recent_decisions` (default 3), `max_pinned` (default 3), `allow` (entries written by `status.py allow`; do not edit by hand), and `sections` (titles for Goal / Now / Next / Blocked / Decisions). `allow` lists the values the user chose to keep despite `check`: for each, a short hash of the value, its kind (email address, API key or token, ...), where it was allowed (`STATUS.md:11`) and the date. The value itself is never stored, and only the same value of the same kind is let through, so an edited address is flagged again. In shared mode the list is committed, so it also quiets teammates' `check` and CI: changes to it show in pull requests with their kind and place, and deserve the same review as the helper script. `allow --list` shows the entries, `allow --remove ID` drops one, `allow --reset` clears them all. Missing keys use defaults; invalid values are reported by `check` and fall back to defaults. To move the status file, change `path`, move the file, and run `init` again: it replaces the old path's merge rule with one for the new path, or in personal mode adds the new path to `.git/info/exclude` (the old line stays; it is harmless); `check` warns until then. When the user asks to rename sections, change `sections` in the config *and* the headings in the status file together, otherwise `check` reports missing sections.

## Hooks

In Claude Code, users can also run `check --quiet` from a hook so problems are flagged automatically. Suggest this only if they ask how to make updates more reliable, and test it in their setup.
