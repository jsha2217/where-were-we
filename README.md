# where-were-we

Your own `STATUS.md`, kept out of git, so the next coding-agent session knows where you stopped.

Agents forget everything between sessions. A growing notes file soon costs thousands of tokens and drifts out of date. where-were-we keeps **one short file (max 50 lines)** that says where your work is *now*. Finished work and decisions go to side files you open only when you need them.

- **Personal.** Everything stays on your machine: the files are listed in `.git/info/exclude`, so they never reach a commit, a merge or a pull request, and they survive branch switches.
- **Tiny.** One Python file, standard library only. No server, no database, no installs.
- **Safe with parallel agents.** Several windows and subagents can write at once: writes take turns through a lock and replace files atomically.
- **Automatic in Claude Code.** As a plugin, a hook shows `STATUS.md` to every new session, and another reminds the agent to update it after you commit.

> **Beta (v0.12.0).** Being tested in real projects before 1.0. Features are frozen until then; only bug and doc fixes go in.

## What it keeps

```
STATUS.md                       # current state only, max 50 lines
.where-were-we/decisions.md     # every decision, one line each
.where-were-we/log/YYYY-MM.md   # finished work, by month
```

`STATUS.md` looks like this:

```markdown
# Status
_updated: 2026-11-04_

## Goal
- Ship OAuth login for the web app

## Now
- [ ] Google OAuth callback — not cache or lock; suspect handlers.py

## Next
- GitHub OAuth
- Session expiry tests

## Blocked
- [user] Add a payment card to the Fly.io account

## Decisions
- D-012: Redis cache, not in-memory — several instances planned
- (+9 older: .where-were-we/decisions.md)
```

## Install

### Claude Code plugin (recommended)

The repository is its own plugin marketplace. In Claude Code:

```
/plugin marketplace add jsha2217/where-were-we
/plugin install where-were-we@where-were-we
```

Then, in a project, ask the agent to set it up ("set up where-were-we"). It runs `init`, creates the files and asks you for the Goal.

The plugin adds two hooks:

| Hook | What it does |
|---|---|
| `SessionStart` | Puts `STATUS.md` into every session (startup, resume, clear, compact), so reading it never depends on the agent remembering. |
| `Stop` | When your newest commit is newer than `STATUS.md`, asks the agent once per commit to update it. Commits by others are ignored. |

Hooks do nothing in projects without `STATUS.md`, and never break a session: any error means they stay silent.

### Plain skill (other agents, or without hooks)

Copy `skills/where-were-we/` into your agent's skills folder (for Claude Code, `~/.claude/skills/where-were-we/`). Set up with `init --link`: it also adds a short block to `CLAUDE.local.md` so every session reads `STATUS.md` first.

## Usage

You mostly just talk to the agent: "where were we", "어디까지 했지", "let's continue", "that's done", "let's go with Postgres". The skill tells the agent which command to run. You can also run them yourself from anywhere in the project:

```sh
python3 skills/where-were-we/scripts/status.py <command>
```

| Command | What it does |
|---|---|
| `init [--link]` | Create the files and list them in `.git/info/exclude` (`--link`: also point `CLAUDE.local.md` at `STATUS.md`) |
| `claim 2` / `claim "OAuth"` | Start work: Next item 2 (or the one matching the text) moves into Now; new text is added |
| `done` / `done "OAuth"` | Finish a Now item and log it in `.where-were-we/log/` |
| `decide "Use X, not Y — because Z"` | Record a decision; `STATUS.md` shows the five latest |
| `check` | Is `STATUS.md` still under 50 lines with every section? |

Goal, Next and Blocked are edited by hand. Now changes only through `claim` and `done`.

`STATUS.md` is treated as notes, not instructions: if it ever asks the agent to do something, the agent tells you instead of doing it. Keep secrets and personal data out of it, since every session reads it.

## Uninstall from a project

Delete `STATUS.md` and `.where-were-we/` (decisions and logs go too; they were never committed), the block between the `where-were-we` markers in `CLAUDE.local.md`, and the `# where-were-we` lines in `.git/info/exclude`.

## Requirements

- Python 3.9 or newer, git
- macOS and Linux tested (Python 3.9, 3.12, 3.14). Windows not yet verified.

## Development

```sh
bash tests/run.sh
```

Each test runs in its own temporary `HOME` and git repositories, so nothing outside a temp folder is touched.

```
.claude-plugin/        plugin.json, marketplace.json
hooks/hooks.json       SessionStart and Stop hooks
skills/where-were-we/  SKILL.md and scripts/status.py
tests/                 run.sh and shell tests
```

## License

No license yet (all rights reserved). One will be chosen before the repository goes public.
