---
name: analyze
description: Triage dtest tests of one module (GREEN/YELLOW/RED) and publish the result. Use when asked to "analyze file X", "analyze <module>", "analyze next file", or to continue the triage.
argument-hint: "<module> | next [N]"
---

Run from `~/github/dtest-triage`.

1. Sync: `git pull --rebase -q` (another session may have pushed analyses),
   `git -C ~/github/scylla-dtest fetch -q upstream next`, `git -C ~/github/scylladb fetch -q upstream master`.
2. Pick the module:
   - `<module>` given: dotted name as in `data/index.json` (`cqlsh_tests.cqlsh_copy_tests`); accept a file path
     (`cqlsh_tests/cqlsh_copy_tests.py`) or a bare name and map it.
   - `next`: first module in `python3 scripts/pending.py` output.
   - `next N` / several modules: see "Batch" below.
   Nothing pending for it → say so and stop.
3. Chunks: `python3 scripts/pending.py | grep "^<module> "` → one line per chunk of ≤10 tests.
4. For each chunk, **one at a time** (they write the same file), spawn a general-purpose subagent:
   `Read /home/cezar/github/dtest-triage/.claude/skills/analyze/prompt.md and follow it with {MODULE} = <module> and {TESTS} = <chunk tests>`.
   If the tests are thin wrappers around shared helpers, one subagent may do the whole module in one pass.
   Wait for it, then `python3 scripts/check_analysis.py <module>`; fix/re-run a chunk if it reports problems.
   Check that every issue the subagent reports is in that test's `issues` (kind/tag per prompt.md step 7) and
   `reason`; `check_analysis.py` flags GREEN with a `bug`. Fix the JSON if not.
   If the report contradicts itself (e.g. "helper check can't fail" vs GREEN for "exact counts"), check
   the code: which helper each test calls and what it asserts. Fix the JSON/summary before replying.
5. Done when `check_analysis.py` shows all tests analyzed and no problems. Then:
   `git add analysis/<module>.json && git commit -m "analysis: <module>" && git push -q`.
6. Reply: table of test, decision, short reason; count of GREEN/YELLOW/RED; notable findings
   (e.g. skip marks on closed issues, tests that could return to gating).

## Batch (several modules)

Modules write different files, so run them in parallel: do step 1 once, then spawn one background
general-purpose subagent per module (first N distinct modules of `pending.py`), each told to follow this skill for
its module but skip step 1 and step 5's git add/commit/push, touch only `analysis/<module>.json`, and wait for any
subagents it spawns (a chunk is done only when `check_analysis.py` shows its tests, not when a subagent says so). As each finishes: run `check_analysis.py`, apply the step 4 checks,
`git commit -m "analysis: <module>"` (no push). When all are committed: `git pull --rebase -q && git push -q`.
