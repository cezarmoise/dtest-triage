---
name: removal-prs
description: Apply developer reviews of our scylla-dtest test-removal PRs - record each dev verdict as final in the analysis (keep → GREEN, remove → RED), close Jira issues of kept tests as Won't Fix, and hand the PR changes (drop commits, fix messages/body, follow-up PR for a requested alternative, close the PR) to a Claude in herdr. Use when asked to handle/process reviews or comments on removal PRs, e.g. "/removal-prs 7841" or "/removal-prs" (all with new reviews).
argument-hint: "[PR number ...]"
---

Run from `~/github/dtest-triage`. `$T` = `~/.cache/claude/<session-id>`. `R` = `scripts/removal.py` (docstring:
`prs`, `pr`). Request: `$ARGUMENTS`.

Rule: a developer's review of a removal PR is final. It becomes `review` in the analysis entry (CLAUDE.md contract);
`check_analysis.py` keeps it and the matching decision, the analyze rechecks never re-decide it.
Dev = human reviewer other than the PR author and the QA reviewers added to every PR (pehala, jsmolar, yarongilor;
`R pr` tags them `QA`); bots never count (coderabbit, qodo, copilot). QA comments can still ask for PR changes, but
give no verdict. Two devs disagree on a test → ask the user.

1. Sync: `git pull --rebase -q`; `git -C ~/github/scylla-dtest fetch -q upstream next`;
   `git -C ~/github/scylladb fetch -q upstream master`.
2. PRs: the given numbers, else `R prs` lines with `new=` > 0, or `dev=` > 0 and `recorded=` < all (a review
   the user answered by hand, verdicts not recorded yet). Per PR `R pr <n> > $T/pr-<n>.md`; read it all.
   NEW items = PR changes not done yet; verdicts come from every dev item.
3. Verdict per test of the PR without a `review` (tests with one are final: leave them; a dev reversing a recorded
   verdict in a later round → stop and ask the user):
   - `keep`: the dev says not to remove it, with or without another action (move out of `next_gating`, fix it,
     "keep until scylla has test X"). The action goes in a follow-up PR (a removal PR stays one kind).
   - `remove`: the dev accepts the removal, also with text/code fixes (an APPROVED review with no remark on a test
     counts as `remove` for it).
   - none: not addressed, or only a question → no `review`; questions go to the user.
   Clear → go on; ambiguous (hedged wording, conflicting devs, "maybe") → show the table, ask once.
4. Analysis, per test with a verdict (`analysis/<module>.json`):
   - `review` = `{"by": "<Name> (<login>)", "url", "date", "pr", "verdict"}`: url = the comment about that test
     (inline thread) if any, else the review; name from `R pr`.
   - `keep`: `decision` GREEN; `reason` = `Per <Name> (<login>) <url>: <why keep, 1-2 sentences>; <the action
     instead, if any>.` Old removal arguments that the dev refuted go; issues stay.
   - `remove`: `decision` stays RED; prefix `reason` with `Per <Name> (<login>) <url>: removal accepted.`
   - Both: fix what the dev corrected: `duplicates` (drop a cited test that doesn't check it, e.g. a vacuous one;
     add the right ones with their notes; gaps the dev named go in the duplicate's `note`), wrong facts in
     `description`/`relevance`. Keep `jira`.
   `python3 scripts/check_analysis.py <modules>`, then `git commit -m "analysis: review #<n>" analysis/`,
   `git pull --rebase -q && git push -q`.
5. Jira (kept tests with `jira`): `python3 scripts/jira_sync.py <keys>` (dry run, after the push) must print
   `<key> CLOSE Won't Fix` with the new reason as the comment (SKIP = the key still has a RED test: leave it out,
   report). The CLOSE keys go in the handoff: the herdr agent closes them once the PR work is done.
6. PR work needed only for NEW items asking for something (keep, fixes, questions to answer). None (e.g. an
   approval, or a review the user already handled) → skip steps 6-7 for that PR; CLOSE keys left → hand the user
   `! python3 scripts/jira_sync.py --apply <keys>` (auto mode blocks Jira writes here).
   Handoff `$T/pr-<n>.handoff.md`, absolute paths (the other session has no `$T`):
   ```
   Apply the dev review of https://github.com/scylladb/scylla-dtest/pull/<n>: follow
   /home/cezar/github/dtest-triage/.claude/skills/removal-prs/review.md.
   Requested by the user ("/removal-prs <args>"): you may rewrite the branch and push it with --force-with-lease,
   open a follow-up PR, close this PR, reply and comment on GitHub, close the Jira issues below as Won't Fix,
   and once this PR is closed delete its branch (origin and local) and this worktree.
   Worktree: <path>, branch <branch>
   Review material: <abs $T>/pr-<n>.md
   Tests, in commit order:
   <sha10> <TEST>: remove | remove + fixes (<what>, <url>) | keep, drop the commit (<url>)
                 | keep + follow-up: <action> (<url>)
   PR-level: <cover letter / body fixes, nits, with urls | none>
   Drop from Closes: <jira keys of kept tests | none>
   Close as Won't Fix: <CLOSE keys of step 5 | none>
   Not ours: <scylla follow-ups the dev proposed, questions left for the user | none>
   ```
7. Herdr: `test "$HERDR_ENV" = 1`, else stop and give the user the handoff path.
   - Worktree gone (`R pr` says `-`): `cd ~/github/scylla-dtest && command wt switch --no-cd <branch> --format json`.
   - `herdr worktree open --cwd ~/github/scylla-dtest --path <path> --label <branch> --no-focus`.
     Not open before → `.result.root_pane.pane_id`, `sleep 2`, `herdr agent start <name> --kind claude --pane <id>`
     (name `rv-<n>`, `agent_not_ready` → ask the user to answer the dialog, then `herdr agent wait <name>
     --timeout 300000`).
     `already_open` → `herdr agent list`: a claude agent whose `cwd` is the worktree and `idle`/`done` → use it
     (likely the PR's author, knows it); `working`/`blocked` → stop, report; none → a shell pane of that workspace
     (`herdr pane list --workspace <id>`) and start one as above.
   - `herdr agent prompt <agent> "Read <abs handoff> and follow it."`; a few seconds later `herdr agent get` says
     `working`. Reused agent: first `herdr agent read <agent> --source visible` — text on its `❯` input line = the
     user is typing there: don't prompt, give the user the line to send.
8. Reply per PR: test → verdict (dev, link) → analysis change; Jira keys the agent closes (or the command for the
   user); herdr workspace + agent;
   scylla follow-ups the dev proposed (for the user to file); questions. The agent reports PR URLs in its pane.
   A closed PR's branch and worktree go (the agent does it when it closes one; `R` treats branches as pending
   removals). Other `CLEANUP` lines of `R prs` (closed or merged elsewhere): do them here, step 9.
9. Cleanup, per `CLEANUP #<n> <state> <branch>` line of `R prs`: no herdr agent `working` in the worktree (else
   skip, report); `origin=yes` → `git -C ~/github/scylla-dtest push -q origin --delete <branch>`; then
   `cd ~/github/scylla-dtest && command wt remove -D --foreground <branch>` (dirty worktree → skip, report).
   Its herdr workspace, if open: `herdr workspace list` → `herdr workspace close <id>` (none `working`).
