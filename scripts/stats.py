#!/usr/bin/env python3
"""Per-test stats from *_long.csv: pass rate, avg duration (all / last 5 runs). Skipped runs excluded."""
import csv
import sys
from collections import defaultdict

runs = defaultdict(list)
for r in csv.DictReader(open(sys.argv[1])):
    if r["status"] != "SKIPPED":
        runs[r["test"]].append((int(r["build"]), r["status"], float(r["duration"])))

w = csv.writer(sys.stdout)
w.writerow(["test", "runs", "pass_rate_pct", "avg_s_all", "avg_s_last5", "last5_vs_all_pct"])
for t, rs in sorted(runs.items()):
    rs.sort()
    avg = sum(d for *_, d in rs) / len(rs)
    last5 = sum(d for *_, d in rs[-5:]) / len(rs[-5:])
    passed = sum(s == "PASSED" for _, s, _ in rs)
    w.writerow([t, len(rs), round(100 * passed / len(rs), 1), round(avg, 1), round(last5, 1),
                round(100 * (last5 - avg) / avg, 1) if avg else ""])
