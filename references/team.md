# Team mode (experimental)

Team mode has had less testing than solo and personal use; tell the user so when they turn it on.

When several people (and their agents) work on one project, a single Now list mixes everyone's work and conflicts on every merge. Team mode splits it: STATUS.md keeps the shared parts (Goal, Next, Blocked, Decisions) and each person's Now lives in `.where-were-we/now/<name>.md`, which only they edit.

- **Set up once per project, after the team agrees**: `init --team` (or run it on an existing project to switch; shared Now items move into the current person's file).
- **Once per person and clone**: `whoami mk`. A short name only (initials or a handle, never a full name or email); it is stored in the clone's git config, not committed. If it is not set, team commands say so; ask the user what name to use.
- **Taking work**: `claim "OAuth"` moves the Next item containing that text into your Now, so two people do not pick up the same thing. Prefer text to numbers (`claim 2`): numbers shift when someone else claims first. `claim "Fix flaky test"` adds something new. `release` puts an item back at the top of Next.
- **Several agents of your own** (e.g. one per worktree) can each `claim` work; your Now file merges cleanly when the branches come together.
- **Finishing**: `done` works on your own Now and logs the item with your name.
- **Seeing the team**: `team --fetch` reads every branch's `.where-were-we/now/` files without checking anything out, so you see what a teammate is doing on `feature/pay` before it is merged. Use it at the start of a session and before claiming, and avoid work someone else has in progress. `claim` itself warns when someone already has the item on any branch this clone knows, and `team` and `check` flag an item that two people hold (after a merge, say): agree who keeps it and have the other `release` it.

Teammates do not need this skill installed: the helper copy and the Project status block in AGENTS.md / CLAUDE.md are in the repo. They only need to pull, run `whoami` once, and push their work so others can see it. Without the skill, though, merges of STATUS.md and the Now files use git's normal merge and may conflict: the section-aware merge helper is registered only from an installed skill, because a helper that ran the repository's own copy would execute whatever was last committed on every `git pull`.
