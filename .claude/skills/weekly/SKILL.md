---
name: weekly
description: Weekly triage update - refresh Jenkins/dtest/scylla, mark deleted tests, recheck tests affected by new dtest commits, closed issues or scylla ports, analyze new tests. Use when asked for the weekly update/refresh or "what changed in dtest".
---

Run from `~/github/dtest-triage`. `$T` = `/tmp/claude/<session-id>`.

1. Sync: `git pull --rebase -q`, `scripts/refresh.sh` (Jenkins CSVs, fetch dtest `next` + scylla `master`,
   `gen_data.py`; takes minutes). Auth/login errors → ask the user to fix.
   Commit: `git add jenkins data cache && git commit -m "data: refresh <date>"`.
2. `python3 scripts/delta.py --apply > $T/delta.txt`. It writes DELETED entries and bumps the revs of modules with
   nothing else to recheck. Line 1: `# dtest_rev <D> scylla_rev <S>`; the rest: `<module> <key> <KIND> <detail>`
   (kinds in the script docstring). Many DELETED in one module = suspect (rename/move): check before committing
   `git commit -m "analysis: delta <date>" analysis/`.
3. MOVED: the test was renamed or moved (detail = new `file::Class::test`). Move the entry to the new key (same
   module: rename the key; other module: copy it there if that module has data and set the old one DELETED with
   `deleted.sha` = the commit) and recheck it as CHANGED. `--bump` the old module if it has no other lines.
   Whole file renamed (all its tests MOVED to one new file): `git mv analysis/<old>.json analysis/<new>.json`, fix
   `file` and the keys, `--bump` it, rerun `delta.py <new module>` and recheck what it reports.
4. Before spawning: one helper change hitting many modules (tree-wide refactor) → read its diff yourself. If it can't
   change what tests check (logging, renames, timeouts), drop those HELPER lines, `--bump` modules left with
   no lines, and say so in the reply.
5. Recheck: one background general-purpose subagent per module (modules run in parallel; within a module, chunks of
   ≤10 tests one at a time, they write the same file):
   `Read /home/cezar/github/dtest-triage/.claude/skills/analyze/prompt.md and follow its "Update mode" for
   {MODULE} = <module> with these trigger lines: <lines>`.
   As each finishes: `python3 scripts/check_analysis.py <module>`, the analyze skill's step 4 checks, then
   `python3 scripts/delta.py --bump <D> <S> <module>` and `git commit -m "analysis: weekly <module>" analysis/<module>.json` (only that file: others are in progress).
6. New tests: `python3 scripts/pending.py` → run the analyze skill (batch, skip its step 1) for those modules.
7. `python3 scripts/delta.py` should print only the header (anything left = not done).
   Then `git pull --rebase -q && git push -q`.
8. Reply: decision changes (test, old → new, why), DELETED tests (with their previous decision), new tests
   analyzed, items for a human (MOVED, `*` ports, dropped HELPER lines).
