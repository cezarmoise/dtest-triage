---
name: analyze
description: Triage dtest tests of one module (GREEN/YELLOW/RED) and publish the result. Use when asked to "analyze file X", "analyze <module>", "analyze next file", or to continue the triage.
argument-hint: "<module> | next"
---

Run from `~/github/dtest-triage`.

1. Sync: `git pull --rebase -q` (another session may have pushed analyses),
   `git -C ~/github/scylla-dtest fetch -q upstream next`.
2. Pick the module:
   - `<module>` given: dotted name as in `data/index.json` (`cqlsh_tests.cqlsh_copy_tests`); accept a file path
     (`cqlsh_tests/cqlsh_copy_tests.py`) or a bare name and map it.
   - `next`: first module in `python3 scripts/pending.py` output.
   Nothing pending for it → say so and stop.
3. Chunks: `python3 scripts/pending.py | grep "^<module> "` → one line per chunk of ≤10 tests.
4. For each chunk, **one at a time** (they write the same file), spawn a general-purpose subagent:
   `Read /home/cezar/github/dtest-triage/analyze_prompt.md and follow it with {MODULE} = <module> and {TESTS} = <chunk tests>`.
   Wait for it, then `python3 scripts/check_analysis.py <module>`; fix/re-run a chunk if it reports problems.
5. Done when `check_analysis.py` shows all tests analyzed and no problems. Then:
   `git add analysis/<module>.json && git commit -m "analysis: <module>" && git push -q`.
6. Reply: table of test, decision, short reason; count of GREEN/YELLOW/RED; notable findings
   (e.g. skip marks on closed issues, tests that could return to gating).
