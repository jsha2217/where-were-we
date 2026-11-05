# Worktrees, settings and upgrading

## Out of git

`init` lists `STATUS.md`, `.where-were-we/` and `CLAUDE.local.md` in `.git/info/exclude`, a local ignore list that is never committed. Nothing shows in `git status` or a pull request, `git add -A` skips them, and they stay put when the user switches, merges or rebases branches: the file describes the user's work, not a branch. Trade-off: they are not backed up through git and do not follow the user to another clone or machine. Outside git there is nothing to exclude.

If the repository has its own committed `STATUS.md`, `init` refuses to take it over; use `init --path .where-were-we/STATUS.md`.

## Worktrees and parallel agents

A linked git worktree does not get a copy of the files (git never copies ignored files); commands run there use the main worktree's, and `check` says so. Several agent windows may update the files at once: the helper takes turns with a lock and writes atomically, so nothing is lost.

## Staleness

`check` warns when the user has made `stale_after_commits` (default 5) commits since STATUS.md was last edited.

## Settings

`.where-were-we/config.json` is created by `init` and can be left alone. Keys: `path` (where the status file lives; for a new setup `init --path` sets it), `language` (`en` or `ko`), `max_lines`, `max_line_length`, `stale_after_commits`, `recent_decisions` (default 3), `max_pinned` (default 3), and `sections` (titles for Goal / Now / Next / Blocked / Decisions). Missing keys use defaults; invalid values are reported by `check` and fall back to defaults.

To move the status file, change `path`, move the file, and run `init` again so the new path is excluded; `check` warns until then. When the user asks to rename sections, change `sections` in the config *and* the headings in the status file together, otherwise `check` reports missing sections.

## Hooks

In Claude Code, users can run `check --quiet` from a hook so problems are flagged automatically. Suggest this only if they ask how to make updates more reliable, and test it in their setup.

## Upgrading from an older shared setup

Versions before 0.10 could commit the files, add merge rules to `.gitattributes`, keep a helper copy at `.where-were-we/status.py` and run a team mode. `check` reports what is left; `init` cleans it up (old settings, `.gitattributes` lines it wrote, the helper copy, the merge helper and team name in git config) and leaves the user's own lines alone. Two steps need the user:

- Files git still tracks: `git rm -r --cached STATUS.md .where-were-we`, then commit. The files stay on disk. Teammates who pulled them keep their copies until they delete them.
- An old Project status block in `CLAUDE.md` or `AGENTS.md`: `init --link` moves it to `CLAUDE.local.md`. It edits those files, so ask first.
