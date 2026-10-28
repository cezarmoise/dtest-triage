#!/usr/bin/env python3
"""Jenkins test results → <out>_long.csv, one row per run (build, split, test, status, duration).

Merges into the existing file: fetches finished builds not in it, keeps the newest N builds with results
(Jenkins keeps only ~30). Builds without results (failed early, report missing) are retried next time.
"""
import argparse
import csv
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

JENKINS = "https://jenkins.scylladb.com"
CASES = "suites[enclosingBlockNames,cases[className,name,status,duration]]"
FIELDS = ["build", "split", "test", "status", "duration"]


def get(url):
    out = subprocess.run(["curl", "-n", "-sS", "-g", "-f", url], capture_output=True, check=True, text=True).stdout
    return json.loads(out)


def report(job_url, number, stage=None):
    try:
        data = get(f"{job_url}/{number}/testReport/api/json?tree={CASES}")
    except subprocess.CalledProcessError:
        return []
    # PASSED/FIXED -> PASSED, FAILED/REGRESSION -> FAILED, SKIPPED
    norm = {"FIXED": "PASSED", "REGRESSION": "FAILED"}
    rows = []
    for s in data["suites"]:
        blocks = s.get("enclosingBlockNames") or [""]
        if stage and not any(stage in b for b in blocks):
            continue
        rows += [{"build": number, "split": blocks[0], "test": f"{c['className']}.{c['name']}",
                  "status": norm.get(c["status"], c["status"]), "duration": c["duration"]} for c in s["cases"]]
    return sorted(rows, key=lambda r: r["test"])  # stable: a test run twice keeps its suite order


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--job", default="scylla-master/dtest-release")
    p.add_argument("-n", "--builds", type=int, default=50, help="keep the newest N builds with results")
    p.add_argument("-o", "--out", default="results")
    p.add_argument("--stage", help="only suites from pipeline stages containing this, e.g. 'dtest with tablets'")
    a = p.parse_args()

    path = Path(f"{a.out}_long.csv")
    old = list(csv.DictReader(path.open())) if path.exists() else []
    have = {int(r["build"]) for r in old}
    job_url = f"{JENKINS}/job/" + "/job/".join(a.job.split("/"))
    # running builds can have partial results (pipeline stages publish as they finish)
    builds = [b["number"] for b in get(f"{job_url}/api/json?tree=builds[number,building]{{0,{a.builds}}}")["builds"]
              if not b["building"] and b["number"] not in have]
    with ThreadPoolExecutor(8) as ex:
        new = [r for rows in ex.map(lambda n: report(job_url, n, a.stage), builds) for r in rows]

    keep = set(sorted(have | {r["build"] for r in new}, reverse=True)[:a.builds])
    rows = sorted((r for r in new + old if int(r["build"]) in keep), key=lambda r: -int(r["build"]))
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{path}: {len({r['build'] for r in new})}/{len(builds)} new builds with results, {len(keep)} kept",
          file=sys.stderr)


if __name__ == "__main__":
    main()
