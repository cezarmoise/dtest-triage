Build a claude.ai Artifact: **dtest triage dashboard**. Single HTML page, vanilla JS, no external libs.

## Purpose
Decide for each scylla-dtest test: GREEN = keep, YELLOW = needs second opinion, RED = remove.
Data is generated offline and pushed to public repo https://github.com/cezarmoise/dtest-triage (branch `main`).

## Data source (read-only)
- `data/index.json` — list of module names, e.g. `["alternator_stream_tests", ...]`
- `data/<module>.json` — generated:
  `{file, rev, tests: [{class, name, lines, stats: {runs, pass_rate, avg_s}, params: {"[p]": stats},
    commits: [{sha, date, author, subject, pr: {number, title} | null}]}], file_commits: [same shape]}`
  Commits are newest first. Stats = Jenkins `scylla-master/dtest-release`, last 20 builds.
- `analysis/<module>.json` — LLM analysis, may be missing (→ tests are GRAY):
  `{file, analyzed_at, scylla_rev, tests: {"<Class>::<test>": {description, origin: {sha, date, pr, summary},
    commits: {"<sha>": "1-line summary"}, relevance, duplicates: [{path, coverage, note}], decision, reason}}}`
  Commit keys may be short or full shas — match by prefix.

Load via, in order of preference:
1. `network` capability allowing `https://raw.githubusercontent.com` → `fetch(raw.githubusercontent.com/cezarmoise/dtest-triage/main/<path>)`.
2. Viewer's GitHub connector via `mcp` (`get_file_contents`, owner `cezarmoise`, repo `dtest-triage`).
Show a clear error if neither works.

## Human decisions (read-write, shared)
Use the shared Artifact `db`, live via `onSnapshot`. Collection `decisions`, doc id `<module>::<Class>::<test>`:
`{decision: GREEN|YELLOW|RED, note, by (from user capability), at}`. Keep a history (append, don't overwrite).
Effective decision = latest human decision > analysis.decision > GRAY.
Per test: 3 buttons (GREEN / YELLOW / RED) + note field. Show who decided, and the LLM decision if overridden.

## Layout
- Header totals: files, tests, GREEN / YELLOW / RED / GRAY counts.
- Table, one row per test file: name | GREEN | YELLOW | RED | GRAY | total. Expandable.
  - File → test classes (same count columns), expandable.
    - Class → tests: decision badge, name, pass rate, avg duration. Expandable.
      - Test body: description, decision reason, relevance, duplicates (coverage, path, note),
        origin (date, sha link, PR link, summary), Jenkins stats (+ per-param table if params),
        commits touching the test (newest first): date, sha → `github.com/scylladb/scylla-dtest/commit/<sha>`,
        PR → `.../pull/<n>`, LLM summary (fallback: subject), author.
        Then file-level commits that the analysis summarized (in `analysis.commits` but not in the test's `commits`).
- Filters: by effective decision, text search on test name, "disagreements only" (human ≠ LLM).
- Sort files by name; option to sort by RED count or GRAY count.

Reference implementation (static, no db): `index.html` in the same repo — reuse its rendering logic.
