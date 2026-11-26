# Removal PR (run by a Claude in a scylla-dtest worktree)

Input: the handoff file (worktree, branch, kind, material, Closes, Reviewers, tests). Work only in the worktree; don't touch
`~/github/dtest-triage` or the main `~/github/scylla-dtest` checkout.
`R` = `/home/cezar/github/dtest-triage/scripts/removal.py` (executable; docstring explains `strip` and `collect-diff`).
zsh: a variable holding `python3 <path>` doesn't word-split (`$R …` → exit 127): keep `R` one word.
zsh: `${v}` before a `:` (`$sha:path`, `$v:c…` are modifiers): write `"${sha}:path"`.
`V` = `$HOME/github/scylla-dtest/.venv-dtest-$(cat .python-version)/bin`.
Run ruff/pytest only through `R`, `$V/ruff` or `$V/python -m pytest` (not on `PATH`).

1. Per test, in the handoff order, one commit each:
   a. `R strip <module>::<Class>::<test>`: removes it where it's defined (`defined_in` if inherited) with its
      decorators, drops imports it made unused, formats. A failure explains itself: fix it or ask the user.
   b. `candidates` = defs nothing references anymore. Strip the ones that only served this test, in this same commit
      (`R strip <file>::<Class>::<name>` or `<file>::<name>`), and repeat on the new candidates. Keep generic code
      under `tools/` (list it in the PR body as dead but kept) and parameters of sctool/CLI wrappers.
      `still referenced` = in use: keep it (`--force` only when the hit is an unrelated same-named def).
   c. Message file (`git commit -F`):
      - subject `<file stem>: remove <test>` (e.g. `alternator_tests: remove test_x`);
      - body wrapped at 72 (URLs, identifiers may run over), from the material:
        covered: `Covered by <repo> <test id>: <what it checks>.` with the permalink on its own line; then what the
        dtest checked that the duplicate doesn't, if the note/reason says so, and other facts from the reason
        (bug, slow, params running the same check).
        bug: what's wrong (the `bug` issue) and why fixing it isn't worth it (reason).
        other: why it's obsolete or low value, with the evidence (commit, PR, issue).
        Removed helpers: `It was the last user of <X>, drop it.`
      - no Jira keys, no Co-authored-by, no Signed-off-by.
   d. `PATH=$V:$PATH git commit -q -a -F <file>` (the pre-commit hook runs ruff from PATH; never `--no-verify`).
      Hook rewrote files → `git add -u`, commit again.
2. Check:
   - `R collect-diff <every test of the handoff>` prints `OK`. Unexpected removals (a test inherited elsewhere, a
     shared helper) → stop and ask the user.
   - `git log --oneline upstream/next..HEAD`: one commit per test. `git diff --stat upstream/next...HEAD`: deletions
     (plus rewritten import lines).
   - Labels: `backport/none` only (agreed with the devs: test removals are never backported), and
     `area/test_efficiency` (marks the triage PRs: `removal.py prs` lists ours by it).
3. `git push -u origin <branch>` (origin = cezarmoise fork; never a bare `git push`).
4. PR body file (Markdown):
   - 1-2 sentences: what is removed and why; "One commit per test; each message names the covering test with a
     permalink." (adapt for bug/other).
   - Table `| dtest | covered by |` (or `| dtest | why |`), tests as `<file stem>::<test>`.
   - Gaps worth a look: what the duplicates don't check, from notes/reasons. Only real ones.
   - Removed helpers and dead-but-kept code.
   - One `Closes: <key>` line per key of the handoff's Closes.
   - Sections of `.github/pull_request_template.md`. Testing: tick only what ran: pre-commit ruff, `collect-diff`
     (N tests / M items gone, nothing else); "No Jenkins run" unticked. Pre-checks: backport label ticked
     (`backport/none`: test removals aren't backported), no debug code ticked, `test/tablets` / `test/no-tablets` not needed.
   `gh pr create -R scylladb/scylla-dtest --base next --head cezarmoise:<branch> --title "<title>" --body-file <file>
   --reviewer scylladb/dtest-maintainers[,<handoff Reviewers>] --assignee cezarmoise --label backport/none,area/test_efficiency`
   (the team + the review group's devs from groups.json, nothing else; not a draft: the owner wants reviewers at
   creation). Title like `alternator_tests: remove tests covered by test/alternator` or
   `manager tests: remove tests covered by scylla-manager integration tests`.
5. `gh pr view <n> -R scylladb/scylla-dtest --json commits,reviewRequests,labels` matches; reply with the PR URL and
   one line per test. Leave the worktree in place.
