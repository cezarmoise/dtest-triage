# Apply a dev review to a removal PR (run by a Claude in the PR's scylla-dtest worktree)

Input: the handoff (PR, worktree, branch, verdict per test, PR-level fixes, Closes keys to drop, Jira keys to close).
The verdicts are decided: don't re-argue them. The analysis is already updated and pushed: don't touch
`~/github/dtest-triage` (except running its scripts) or the main `~/github/scylla-dtest` checkout.
`R`, `V`, ruff/pytest/zsh rules, commit message style, checks, backport labels, PR body sections: as in
`/home/cezar/github/dtest-triage/.claude/skills/remove-tests/pr.md`. Commits always `PATH=$V:$PATH git commit`
(hook runs ruff; never `--no-verify`).

0. State: `git fetch -q upstream next`; tree clean; `git rev-parse HEAD` = PR head
   (`gh pr view <n> -R scylladb/scylla-dtest --json headRefOid,body,labels`), else stop and ask. Read the material
   and the review threads it links. Base = `git merge-base HEAD upstream/next` (don't rebase onto a newer next).
   Before rewriting: `git branch backup-<n> HEAD` (compare with it after the rewrite; delete it after the push).
1. Reviewer-proposed diffs, messages and permalinks: check each against the tree and the cited code before using it
   (names imported, lines exist, claim true). Wrong or not applicable → don't apply, say why in the reply (step 4).
2. Follow-up PR, per `keep + follow-up`:
   - `cd ~/github/scylla-dtest && command wt switch --no-cd -c <branch> -b upstream/next --format json` → path;
     branch `<file stem>-<action>` (e.g. `alternator-streams-unmark-gating`), lowercase, ≤ 50 chars, new.
   - Make the change there, one commit; message: the dev's proposed one if they gave one (checked), else pr.md
     style; body ends with `Requested in the review of scylladb/scylla-dtest#<n>:` + the comment URL on its own line.
   - Show it works: e.g. a gating change → count the collected `<file>::<Class>::<test>` lines (the unmark plugin
     logs a `Deselecting …` line with the name, don't grep that) of `$V/python -m pytest --collect-only -q -m
     next_gating <file>`: 0; with `-m "dtest_full and (not next_gating or unmark_if)"` (full suite): 1.
   - `git push -u origin <branch>`; `gh pr create -R scylladb/scylla-dtest --base next --head cezarmoise:<branch>
     --reviewer scylladb/dtest-maintainers[,<logins>] --assignee cezarmoise --label area/test_efficiency,<labels>` (logins =
     the review groups of the kept tests: `R info <tests> | grep ^Reviewers:`; nothing else; the area label lists it
     in `removal.py prs`); body: what + why;
     `Follow-up to #<n>: <Name> (@<login>) asked for this instead of removing the test: <comment url>`; template
     sections; no `Closes:` (the Jira issue is closed Won't Fix). Labels (not a removal, so it may be backported):
     live releases = the plain `backport/<ver>` labels of `gh label list -R scylladb/scylla-dtest --search backport`
     (not `-done`, skip `manager-*`); `<ver>` gets `backport/<ver>` only if `upstream/branch-<ver>` (fetch first)
     has the changed code and the change matters there; none → `backport/none`.
3. Original PR:
   a. No `remove` test left → `gh pr comment <n> --body-file <f>` (per kept test: the dev's point in one line +
      comment URL; the follow-up PR), `gh pr close <n>`. Then steps 4-5, then 3c, then 6.
   b. Otherwise rewrite the branch:
      - Drop each kept test's commit, newest first (shas of later commits change after each rebase; re-read
        `git log --oneline <base>..` between drops): `git rebase -q --onto <sha>^ <sha>`. Conflict (a later commit
        touched the same lines, e.g. a shared helper or import) → resolve keeping the later commit's intent minus
        what the kept test needs, `git rebase --continue`; unsure → `git rebase --abort`, ask the user.
      - Later commits may have removed helpers the kept test still uses: ruff (F821) / `R collect-diff` show it.
        Restore them inside the commit that removed them (`git commit --fixup=<that sha>`), and fix its message
        (`It was the last user of X` no longer true).
      - Code fixes asked for a commit: `git commit --fixup=<sha>`. New message for a commit: empty commit with
        `git commit --allow-empty -F <f>`, `<f>` = `amend! <exact old subject>`, blank line, full new message
        (`--fixup=reword:` needs an editor). Then `git rebase -q --autosquash --exec "$V/ruff check -q <files> &&
        $V/ruff format -q --check <files>" <base>` (rebase skips the commit hook: this checks every commit);
        no `fixup!`/`amend!` left.
      - pr.md step 2 checks with the remaining tests (`collect-diff` OK, one commit per test); labels: `backport/none`
        only (swap any other `backport/*` with `gh pr edit --remove-label … --add-label backport/none`).
      - `git push --force-with-lease origin <branch>`.
      - Body (`gh pr edit <n> --body-file`): apply the dev's cover-letter fixes (checked); kept tests out of the
        table, counts, gaps, helpers and `Closes:`; add `### Kept after review`: per test, one line + comment URL
        (+ follow-up PR).
   c. Closed PR, last (after steps 4-5): `git push -q origin --delete <branch>`, then from the main checkout
      `cd ~/github/scylla-dtest && command wt remove -D --foreground <branch>` (this worktree; the follow-up PR's
      stays). The herdr workspace stays: the user closes it. Run each as its own command; blocked by permissions →
      ask the user in the pane to run them with `!`.
4. Jira, handoff's "Close as Won't Fix" keys, once the PRs are done:
   `python3 /home/cezar/github/dtest-triage/scripts/jira_sync.py <keys>` (dry run): every key must print
   `CLOSE Won't Fix` (anything else → don't apply, report), then the same with `--apply` (posts the new reason as
   comment, transitions; parents are left to `/weekly`). Follow-up PR opened → add `--note "Follow-up: <PR url>"`
   (dry run and apply). Blocked by permissions → ask the user in the pane to run
   `! python3 /home/cezar/github/dtest-triage/scripts/jira_sync.py --apply [--note …] <keys>`.
5. Replies: each handled NEW inline thread → `gh api -X POST repos/scylladb/scylla-dtest/pulls/<n>/comments/<id>/replies
   -f body=...`, 1-2 lines (what changed, in which commit / PR; or why not applied; scylla follow-ups: "left for a
   scylla follow-up"). Refs to other repos in full (`scylladb/scylladb#20191`): a bare `#N` links to scylla-dtest. Open PR: one PR comment summarizing the changes per review (link it), then
   `gh pr edit <n> --add-reviewer <dev login>` (re-request).
6. Reply in the pane: PR URLs (original: updated/closed; follow-up), Jira keys closed, per test what happened, what wasn't applied and
   why, scylla follow-ups the dev proposed. Open PRs keep their worktrees.
