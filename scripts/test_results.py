#!/usr/bin/env python3
"""Rebuild Jenkins test_results_analyzer tables (status + runtime) as CSVs via REST API."""
import argparse
import csv
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

JENKINS = "https://jenkins.scylladb.com"
CASES = "suites[enclosingBlockNames,cases[className,name,status,duration]]"


def get(url):
    out = subprocess.run(["curl", "-n", "-sS", "-g", "-f", url], capture_output=True, check=True, text=True).stdout
    return json.loads(out)


def report(job_url, number):
    try:
        data = get(f"{job_url}/{number}/testReport/api/json?tree={CASES}")
    except subprocess.CalledProcessError:
        return number, {}
    # PASSED/FIXED -> PASSED, FAILED/REGRESSION -> FAILED, SKIPPED
    norm = {"FIXED": "PASSED", "REGRESSION": "FAILED"}
    # same test may run in several suites (separate pytest runs); key by occurrence
    seen, res = {}, {}
    for s in data["suites"]:
        for c in s["cases"]:
            t = f"{c['className']}.{c['name']}"
            seen[t] = seen.get(t, 0) + 1
            split = (s.get("enclosingBlockNames") or [""])[0]
            res[(t, seen[t])] = (norm.get(c["status"], c["status"]), c["duration"], split)
    return number, res


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--job", default="scylla-master/dtest-release")
    p.add_argument("-n", "--builds", type=int, default=10)
    p.add_argument("-o", "--out", default="results")
    a = p.parse_args()

    job_url = f"{JENKINS}/job/" + "/job/".join(a.job.split("/"))
    builds = [b["number"] for b in get(f"{job_url}/api/json?tree=builds[number]{{0,{a.builds}}}")["builds"]]
    with ThreadPoolExecutor(8) as ex:
        reports = dict(ex.map(lambda n: report(job_url, n), builds))

    tests = sorted({t for r in reports.values() for t in r})
    for kind, idx in (("status", 0), ("runtime", 1)):
        path = f"{a.out}_{kind}.csv"
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["test", "run", *builds])
            for t in tests:
                w.writerow([*t, *(reports[b][t][idx] if t in reports[b] else "N/A" for b in builds)])
        print(f"{path}: {len(tests)} tests x {len(builds)} builds", file=sys.stderr)
    with open(f"{a.out}_long.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["build", "split", "test", "status", "duration"])
        for b in builds:
            for (t, _), (status, duration, split) in sorted(reports[b].items()):
                w.writerow([b, split, t, status, duration])


if __name__ == "__main__":
    main()
