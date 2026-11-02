#!/usr/bin/env python3
"""Validate groups.json and print tests per team/group with decision counts. Exit 1 on errors.

Group of a test: first `overrides` pattern (fnmatch on "<module>::<Class>::<test>") that matches, else `modules`.

usage: groups.py
"""
import json
import sys
from collections import Counter, defaultdict
from fnmatch import fnmatchcase
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
G = json.loads((ROOT / "groups.json").read_text())


def group_of(mod, key):
    tid = f"{mod}::{key}"
    return next((g for p, g in G["overrides"].items() if fnmatchcase(tid, p)), G["modules"].get(mod))


def tests():
    """{module: {"<Class>::<test>": decision}}, data + analysis, GRAY if not analyzed."""
    out = {}
    for mod in json.loads((ROOT / "data/index.json").read_text()):
        out[mod] = {f"{t['class']}::{t['name']}": "GRAY"
                    for t in json.loads((ROOT / f"data/{mod}.json").read_text())["tests"]}
    for f in (ROOT / "analysis").glob("*.json"):
        out.setdefault(f.stem, {}).update(
            {k: a["decision"] for k, a in json.loads(f.read_text())["tests"].items()})
    return out


def main():
    all_tests = tests()
    errors = [f"module not in groups.json: {m}" for m in sorted(all_tests.keys() - G["modules"].keys())]
    errors += [f"unknown module: {m}" for m in sorted(G["modules"].keys() - all_tests.keys())]
    used = set(G["modules"].values()) | set(G["overrides"].values())
    errors += [f"unknown group: {g}" for g in sorted(used - G["groups"].keys())]
    errors += [f"unused group: {g}" for g in sorted(G["groups"].keys() - used)]
    errors += [f"{g}: unknown team {v['team']}" for g, v in G["groups"].items()
               if v["team"] and v["team"] not in G["teams"]]
    tids = [f"{m}::{k}" for m, ks in all_tests.items() for k in ks]
    errors += [f"override matches nothing: {p}" for p in G["overrides"]
               if not any(fnmatchcase(t, p) for t in tids)]

    counts = defaultdict(Counter)
    for mod, ks in all_tests.items():
        for k, d in ks.items():
            counts[group_of(mod, k)][d] += 1
    by_team = defaultdict(list)
    for g, v in G["groups"].items():
        by_team[v["team"] or "?"].append(g)
    for team, gs in sorted(by_team.items()):
        print(f"{team}: {sum(sum(counts[g].values()) for g in gs)} tests")
        for g in gs:
            v, c = G["groups"][g], counts[g]
            dec = " ".join(f"{d[0]}{c[d]}" for d in ("GREEN", "YELLOW", "RED", "DELETED", "GRAY") if c[d])
            print(f"  {g:16} {sum(c.values()):4}  {dec:24} [{v['component'] or '-'}] {', '.join(v['reviewers']) or '?'}")
    for e in errors:
        print(e)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
