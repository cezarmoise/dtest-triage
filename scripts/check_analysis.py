#!/usr/bin/env python3
"""Validate analysis/<module>.json against data/<module>.json. Exit 1 on errors.

usage: check_analysis.py MODULE ...
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIELDS = {"description", "origin", "commits", "relevance", "duplicates", "decision", "reason"}

errors = 0
for mod in sys.argv[1:]:
    data = json.loads((ROOT / f"data/{mod}.json").read_text())
    tests = {f"{t['class']}::{t['name']}" for t in data["tests"]}
    analysis = json.loads((ROOT / f"analysis/{mod}.json").read_text())["tests"]
    problems = [f"unknown test {k}" for k in analysis if k not in tests]
    for k, a in analysis.items():
        if missing := FIELDS - a.keys():
            problems.append(f"{k}: missing {sorted(missing)}")
        if a.get("decision") not in ("GREEN", "YELLOW", "RED"):
            problems.append(f"{k}: bad decision {a.get('decision')!r}")
    left = len(tests - analysis.keys())
    print(f"{mod}: {len(analysis)}/{len(tests)} analyzed{f', {left} left' if left else ''}")
    for p in problems:
        print(f"  {p}")
    errors += len(problems)
sys.exit(1 if errors else 0)
