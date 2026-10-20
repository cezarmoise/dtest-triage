# dtest triage (keep / review / remove)

Goal: per dtest test function, decide GREEN=keep, YELLOW=second opinion, RED=remove.
Repo: https://github.com/cezarmoise/dtest-triage (this repo, `~/github/dtest-triage`). Run everything from here.

## Paths

- dtest: `~/github/worktrees/scylla-dtest/test-triage` (worktree; read code at `upstream/next`, `git fetch upstream next` first).
  Main checkout: `~/github/scylla-dtest`.
- scylla: `~/github/scylladb` (read-only; unit/cluster tests under `test/`).

## Layout

```
scripts/test_results.py   # Jenkins → jenkins/<job>_{status,runtime,long}.csv
scripts/stats.py          # per-test stats from a *_long.csv (ad hoc)
scripts/gen_data.py       # jenkins/*_long.csv + dtest git + gh → data/<module>.json, data/index.json
cache/prs.json            # sha → PR {number,title} | null
jenkins/                  # raw Jenkins CSVs
data/                     # generated, overwritten on refresh
analysis/<module>.json    # LLM analysis (per-file subagent, analyze_prompt.md)
analyze_prompt.md         # subagent prompt, {MODULE} placeholder
```

Module = dotted path (`cqlsh_tests.cqlsh_copy_tests` → `cqlsh_tests/cqlsh_copy_tests.py`).

## Refresh

```bash
for j in dtest-release dtest-release-with-raft; do
  python3 scripts/test_results.py --job scylla-master/$j -n 20 -o jenkins/$j; done
python3 scripts/test_results.py --job scylla-master/next -n 20 --stage 'dtest with tablets' -o jenkins/next-dtest-tablets
python3 scripts/test_results.py --job scylla-master/next -n 20 \
  --stage 'dtest with consistent topology changes' -o jenkins/next-dtest-consistent-topology
git -C ~/github/worktrees/scylla-dtest/test-triage fetch upstream next
python3 scripts/gen_data.py [module ...]     # default: all modules in jenkins/*_long.csv
```

## Jenkins data

- Jobs (last 20 builds each, fetched 2026-10-20), name = `jenkins/<name>_*.csv` = key in `stats.by_job`:
  - `dtest-release`, `dtest-release-with-raft` — full dtest runs.
  - `next-dtest-tablets`, `next-dtest-consistent-topology` — gating dtest, stages of `scylla-master/next`
    (filtered by `--stage`). Old `gating-dtest-release-with-{tablets,consistent-topology-changes}` jobs are stale
    since 2026-08-23. Builds that fail before the dtest stages have no results (16/20 had them).
- `*_status.csv` test × build: PASSED / FAILED / SKIPPED / N/A. `*_runtime.csv` duration s.
  `*_long.csv` one row per run (build, split, test, status, duration) — lossless, used by scripts.
- Builds run 4 parallel splits; some tests run twice per build. Skipped runs excluded from stats.
- Plugin RPC (`getExportCSV`) returns 500 via curl, hence REST API.
- Scope: test functions with ≥1 non-skipped run in any job: 1670 functions, 114 modules (~2000 test defs in repo); tests/files gone from `upstream/next` are skipped (e.g. commitlog_test).
  Tests only ever skipped are excluded (e.g. `migration_test.TestTTLWithMigrate.test_big_table_with_ttls`).

## data/<module>.json

`{file, rev, tests: [{class, name, lines, stats, params: {"[p]": stats}, commits}], file_commits}`
`stats = {runs, pass_rate, avg_s, by_job: {<job>: {runs, pass_rate, avg_s}}}` (combined + per job).
Commits newest first: `{sha, date, author, subject, pr}`.
Function history = `git log -L <start>,<end>:file` (ranges from `ast`, `*.py diff=python`); stops at big refactors
(e.g. "port to pytest") → analysis finds real origin from file history.

## Dashboard

claude.ai artifact, reads repo via viewer's GitHub connector
(published artifacts can't fetch raw.githubusercontent.com). Human decisions live in the artifact's shared db
(collection `decisions`, id `<module>::<Class>::<test>`, with history), not in this repo.
Effective decision = human > analysis > GRAY.

## Rubric (agreed 2026-10-20)

- Granularity: per test function; params grouped.
- RED: scylla test fully covers same scenario; tested feature/option/cmd removed; flaky + low-value assertion;
  slow + redundant (covered elsewhere, incl. other dtests); tests Cassandra-only behavior.
- YELLOW: partial overlap, unsure relevance, thin evidence.
- GREEN: unique coverage of live behavior.
- Every non-GREEN needs evidence (scylla test path, commit removing feature, issue link).
- History: function commits + file-level commits that affect the test; formatting commits flagged.

## Status

- Pilot done: alternator_stream_tests (2 tests, both GREEN). Notes: both from c4a3c00e (PR 1977, scylladb/scylla#8012);
  `@unmark.next_gating` cites scylladb/scylladb#15260, now closed → could return to gating.

## Next

1. User reviews pilot; adjust `analyze_prompt.md`.
2. Analysis subagents per module, in parallel, checkpoint per file (`analysis/<module>.json`).
   Big modules (cdc_types_test etc.) may need splitting by class.
