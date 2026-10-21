Triage dtest tests in module `{MODULE}` (file path = `file` in the data JSON) — decide keep / second opinion / remove.

Inputs:
- dtest repo: /home/cezar/github/scylla-dtest. Read code at `upstream/next` (`git show upstream/next:<path>`, path = `file` in the data JSON), not the working tree.
- Generated data: /home/cezar/github/dtest-triage/data/{MODULE}.json — tests in scope (class, name, line range,
  Jenkins stats, last 20 builds per job, per-job breakdown in `stats.by_job`, function-level commits with PRs) + file-level commits.
- Scylla source: ~/github/scylladb (read-only). Unit/cluster tests in `test/` (cluster, cqlpy, alternator, boost, nodetool, rest_api, ...).

Tests to analyze: {TESTS} (`all` = every test in the JSON `tests` list; otherwise only these `Class::test` keys).

For EACH of those tests:
1. Read the test + helpers/fixtures it uses. Origin: the function history may stop at a refactor
   (e.g. "port to pytest"); find the real origin in file-level commits / `git log -S'<name>' upstream/next`.
   The `pr` in the data JSON can be wrong (a later PR containing the commit, e.g. the pytest port); verify it.
   Read origin commit + PR (`gh pr view <n> -R scylladb/scylla-dtest --json title,body`) and any linked scylla issue.
2. Description: what scenario, what is asserted, which scylla bug/feature it guards. 2-5 sentences.
3. Commit summaries: for each function-level commit, 1 line on what it changed IN THIS TEST
   (read `git show <sha> -- <path>`). Mark pure formatting/tree-wide commits as "formatting".
   For file-level commits not in the function list, only summarize those that affect this test's behavior
   (helpers, fixtures, class marks); skip the rest.
4. Relevance: is the behavior still in scylla? grep scylla for the feature, config options, REST/nodetool
   commands, log messages the test relies on. Note feature removals/replacements (e.g. vnodes vs tablets).
5. Duplicates: search scylla `test/` for tests covering the same scenario
   (`grep -ril dtest ~/github/scylladb/test`, `git -C ~/github/scylladb log --grep=<keyword>`, keyword grep in test dirs).
   Also check other dtest files for overlapping tests. Say full / partial / none, with paths::test names.
6. Decision:
   - RED: scylla test fully covers same scenario; tested feature/option/cmd removed; flaky + low-value assertion;
     slow + redundant (covered elsewhere, incl. other dtests); tests Cassandra-only behavior.
   - YELLOW: partial overlap, unsure relevance, thin evidence.
   - GREEN: unique coverage of live behavior.
   Every YELLOW/RED needs concrete evidence (paths, shas, issue links). Don't guess — if unsure, YELLOW.
7. Issues found in the test or its helpers (class-level issues apply to every test of the class): list each in
   `issues` as `{"kind", "tag", "ref", "text"}` (ref = file:line, sha or issue link; text ≤ ~25 words), and mention
   it in `reason` as "Bug: ..." / "Note: ...". `issues: []` if none.
   - kind `bug` = the test checks less than it claims. A bug downgrades GREEN to YELLOW (YELLOW/RED keep theirs).
     Tags: `cant-fail` (assert can't fail, errors swallowed, result ignored), `check-disabled` (commented out,
     unreachable, gated off), `weak-check` (too loose to catch the target bug), `wrong-scenario` (setup/params
     don't exercise what it claims), `never-runs` (not collected, always skipped, empty loop), `log-check-off`
     (`allow_log_errors=True`, ignore patterns hiding real errors), `other`. A mark/filter that still disables
     the test or a check (non-strict xfail on a fixed bug, always-firing skip) is a bug; an inert one is a note.
   - kind `note` = anything else; doesn't change the decision. Tags: `dead-config` (unused option, e.g. `start_rpc`,
     `experimental_features=['cdc']`), `stale-mark` (skip/xfail/require/unmark on a closed issue), `stale-comment`
     (docstring, comment, misleading name), `dead-code`, `redundant-param`, `slow` (fixed sleeps, avoidable
     restarts), `open-issue` (references/catches an open bug), `cosmetic` (typo, assert message), `limited-check`
     (checks less than it could but still catches its target), `other`.
   Not issues: coverage overlap, pass rate, runtime, gating or porting suggestions.
   Name the exact helper (name + file:line) when judging assertion strength; similar helpers may differ
   (e.g. `==` vs `<=`). "Can't fail" claims must hold for the code actually called by that test.

Write /home/cezar/github/dtest-triage/analysis/{MODULE}.json (create dir if needed), schema:
```json
{
  "file": "<path>",
  "analyzed_at": "YYYY-MM-DD",
  "scylla_rev": "<git -C ~/github/scylladb rev-parse --short HEAD>",
  "tests": {
    "<Class>::<test>": {
      "description": "...",
      "origin": {"sha": "...", "date": "...", "pr": 123, "summary": "..."},
      "commits": {"<sha>": "1-line summary"},          // function + relevant file-level commits
      "relevance": "...",
      "duplicates": [{"path": "test/cluster/test_x.py::test_y", "coverage": "full|partial", "note": "..."}],
      "decision": "GREEN|YELLOW|RED",
      "reason": "1-3 sentences, cite evidence; + found issues/bugs",
      "issues": [{"kind": "bug|note", "tag": "cant-fail", "ref": "x_test.py:123", "text": "..."}]
    }
  }
}
```
If the file already exists, load it and add/replace only your tests; keep the other entries.
Write it after every few tests (valid JSON each time), so progress survives interruption.
Do not modify any repo other than writing that file; do not commit. Scratch files/scripts only in your own
`mktemp -d`; never run or reuse existing files in /tmp (old runs left scripts there that overwrite analysis files).
Reply with a short table: test, decision, reason.
