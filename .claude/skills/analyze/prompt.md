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
   Issues/bugs found in the test or its helpers (no-op asserts, dead code/regexes, disabled checks, never-run,
   dead config like `experimental_features=['cdc']` (UNUSED in scylla), refs to closed issues, etc.; class-level
   issues apply to every test of the class):
   always add them to `reason` ("Bug: ..." / "Note: ...", with file:line or sha). Downgrade GREEN to YELLOW;
   YELLOW and RED keep their decision.
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
      "reason": "1-3 sentences, cite evidence; + found issues/bugs"
    }
  }
}
```
If the file already exists, load it and add/replace only your tests; keep the other entries.
Write it after every few tests (valid JSON each time), so progress survives interruption.
Do not modify any repo other than writing that file; do not commit. Reply with a short table: test, decision, reason.
