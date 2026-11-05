# Adopting where-were-we in an existing project

## Starting in a project that is already underway

With no notes to move, fill the file from the project itself: Goal from the README, Now and Next from recent commits, TODOs and open branches. Record choices you can see in the code ("plain SQL, no ORM") as decisions, but as `[proposed]`, since you are inferring them. Do not invent history: the log starts today, and git already holds the past. Show the user the result and ask if it is right.

## Moving an existing notes file in

If the project already has a long status, progress or memory file, ask before touching it. Only the user's own notes are moved: a file other people commit to (a project-status page in a shared repository, say) stays where it is, and the status file goes elsewhere with `init --path .where-were-we/STATUS.md`; `init` stops and says which case applies. Then:

1. Copy it verbatim to `.where-were-we/log/legacy-<date>-<name>.md`, so nothing is lost. If it sits where the new file will go, move it there instead.
2. Run `init`.
3. Carry over only what is true now into Goal, Now, Next and Blocked.
4. Re-record decisions that still hold with `decide`; use `--accepted` only for ones the user confirms now.
5. Run `check`, and show the user the new file next to what was archived.

## Several people committing

If `init` prints that several people have committed here, mention team mode in one sentence when you tell the user what was created. If they will share the file, run `init --team` and read `references/team.md`.
