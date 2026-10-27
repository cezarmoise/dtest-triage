#!/usr/bin/env python3
"""Validate analysis/<module>.json against data/<module>.json. Exit 1 on errors.

usage: check_analysis.py MODULE ...
"""
import json
import sys
from pathlib import Path

from gen_data import locate

ROOT = Path(__file__).resolve().parent.parent
FIELDS = {"description", "origin", "commits", "relevance", "duplicates", "decision", "reason", "issues"}
TAGS = {  # see .claude/skills/analyze/prompt.md step 7
    "bug": {"cant-fail", "check-disabled", "weak-check", "wrong-scenario", "never-runs", "log-check-off", "other"},
    "note": {"dead-config", "stale-mark", "stale-comment", "dead-code", "redundant-param", "slow", "open-issue",
             "cosmetic", "limited-check", "other"},
}

errors = 0
for mod in sys.argv[1:]:
    data = json.loads((ROOT / f"data/{mod}.json").read_text())
    tests = {f"{t['class']}::{t['name']}" for t in data["tests"]}
    full = json.loads((ROOT / f"analysis/{mod}.json").read_text())
    analysis = full["tests"]
    problems = [f"missing {k}" for k in ("dtest_rev", "scylla_rev") if k not in full]
    norun = []
    for k in analysis.keys() - tests:
        if analysis[k].get("decision") == "DELETED":
            continue
        try:  # no runs in the Jenkins window, but still in dtest
            locate(data["file"], *k.split("::"))
            norun.append(k)
        except KeyError:
            problems.append(f"unknown test {k}")
    for k, a in analysis.items():
        if missing := FIELDS - a.keys():
            problems.append(f"{k}: missing {sorted(missing)}")
        if a.get("decision") not in ("GREEN", "YELLOW", "RED", "DELETED"):
            problems.append(f"{k}: bad decision {a.get('decision')!r}")
        d = a.get("deleted")
        if (a.get("decision") == "DELETED") != bool(d) or d and (
                d.keys() != {"sha", "date", "pr", "prev"} or d["prev"] not in ("GREEN", "YELLOW", "RED")):
            problems.append(f"{k}: bad deleted {d!r}")
        issues = a.get("issues", [])
        problems += [f"{k}: bad issue {i}" for i in issues
                     if i.get("tag") not in TAGS.get(i.get("kind"), ()) or not i.get("text")]
        if a.get("decision") == "GREEN" and any(i.get("kind") == "bug" for i in issues):
            problems.append(f"{k}: GREEN with a bug issue")
    left = len(tests - analysis.keys())
    print(f"{mod}: {len(tests) - left}/{len(tests)} analyzed{f', {left} left' if left else ''}"
          f"{f', {len(norun)} without runs' if norun else ''}")
    for p in problems:
        print(f"  {p}")
    errors += len(problems)
sys.exit(1 if errors else 0)
