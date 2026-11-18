---
name: remove-tests
description: Open a scylla-dtest PR removing triaged tests (one commit per test), chosen by a free-text request, e.g. "/remove-tests From alternator_tests.py, only those that are fully covered by another test". Selects and verifies here, creates the dtest branch + worktree with wt, hands the PR to a new Claude in herdr. Use when asked to remove tests or open a removal PR.
argument-hint: "<which tests, in words>"
---

Run from `~/github/dtest-triage`. `$T` = `/tmp/claude/<session-id>`. `R` = `python3 scripts/removal.py` (its
docstring explains subcommands, kinds and statuses). Request: `$ARGUMENTS`.

One PR = one removal kind (`R select` kind column), so reviewers judge one kind of argument:
- `covered`: a full duplicate elsewhere ("fully covered by another test").
- `covered-bug`: covered, but also has a `bug` issue: its own PR (the bug is part of the argument).
- `bug`: removed because it's broken.
- `other`: read `reason`: feature/option removed ("no longer relevant"), low value, Cassandra-only. Separate PRs
  per reason.

1. Sync: `git pull --rebase -q`; `git -C ~/github/scylla-dtest fetch -q upstream next`;
   `git -C ~/github/scylladb fetch -q upstream master`; `git -C ~/github/scylla-manager fetch -q upstream master`.
2. Select: turn the request into `R select` filters (`--module`, `--kind`, `--dup-repo`, `--group`, `--decision`);
   read `reason` when the request needs judgment. Rules:
   - RED only, unless the request names YELLOW. Never GREEN.
   - Only the kind the request asks for. Other kinds in the same scope: list them in the reply as candidates for
     separate PRs, don't add them.
   - `pending=<branch>`: already removed on that branch: drop, report.
   - Request ambiguous about scope or kind: ask once.
3. Verify: `R info <tests> > $T/check.md` (exit 1 = some tests BLOCKED). For each BLOCKED test:
   - `unverified`: check the cited test yourself in its repo at the latest upstream (other repos, e.g. scylla-cqlsh:
     `gh api`). Exists and fits the note → keep the test, note `<test>: verified by hand <permalink>`; else drop it.
   - `dup-selected` (two selected tests cite each other): remove only the narrower one; the broader one (or the
     one in gating) stays in dtest, so drop it from the list. Note which.
   - `missing`, `dup-red`, `dup-pending`: drop.
   Then regenerate the material from the final list: `R info <final tests> > $T/<branch>.md`. Its `Closes:` header
   is the one to use (computed for the final list); BLOCKED lines left in it are the hand-verified ones.
4. Confirm: go on without asking only if every test is RED, one kind and verified. Otherwise show the list, ask once.
5. Branch + worktree (scylla-dtest, not this repo): name `remove-<scope>-<kind>` (e.g. `remove-alternator-covered`),
   lowercase, ≤ 50 chars, not on `git -C ~/github/scylla-dtest branch -a`. Then
   `cd ~/github/scylla-dtest && command wt switch --no-cd -c <branch> -b upstream/next --format json` → `.path`
   (worktree under `~/github/worktrees/scylla-dtest/`). Check `git -C <path> rev-parse HEAD` = `upstream/next`.
6. Handoff `$T/<branch>.handoff.md`; the other session has no `$T`: write absolute paths here and in step 7.
   ```
   Create the scylla-dtest PR removing the tests below: follow
   /home/cezar/github/dtest-triage/.claude/skills/remove-tests/pr.md.
   Requested by the user ("/remove-tests <request>"): you may commit, push the branch to origin and open the PR.
   Worktree: <path>, branch <branch>, from upstream/next <sha10>
   Kind: <kind>: <why these are removed, one line>
   Material: $T/<branch>.md (per test: reason, issues, verified duplicates with permalinks)
   Closes: <keys from the material header | none>
   Tests, in commit order (grouped by file):
   <module>::<Class>::<test>
   Notes: <hand-verified duplicates with permalinks, dup-selected partners kept in dtest, ...>
   ```
7. Herdr: `test "$HERDR_ENV" = 1`, else stop and give the user the worktree and handoff paths.
   - `herdr worktree open --cwd ~/github/scylla-dtest --path <path> --label <branch> --no-focus` →
     `.result.root_pane.pane_id`. `already_open: true` → stop, report.
   - `sleep 2` (let the shell reach its prompt), then `herdr agent start <name> --kind claude --pane <pane id>`;
     name = `rm-` + branch, `[a-z0-9_-]`, ≤ 32 chars.
     `agent_not_ready` (dialog) → ask the user to answer it in that workspace, then
     `herdr agent wait <name> --timeout 300000`.
   - `herdr agent prompt <name> "Read $T/<branch>.handoff.md and follow it."` (no `--wait`); a few seconds later
     `herdr agent get <name>` should say `working`.
8. Reply: N tests, kind, branch, herdr workspace + agent name; table of test → covered by (or why); dropped tests
   and why; other-kind tests left for separate PRs. The agent reports the PR URL in its pane.
