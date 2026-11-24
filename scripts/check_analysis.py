#!/usr/bin/env python3
"""Validate analysis/<module>.json against data/<module>.json. Exit 1 on errors.

usage: check_analysis.py MODULE ...

Also: a test cited as a `full` dtest duplicate of a test whose `review` accepted its removal can't be RED.
"""
import json
import re
import subprocess
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

REVIEW_KEYS = {"by", "url", "date", "pr", "verdict"}
REVIEW_FINAL = {"url", "verdict"}  # can't change once committed
VERDICT = {"keep": "GREEN", "remove": "RED"}

DTEST_PATH = re.compile(r"(?!test/)([\w/]+)\.py::(\w+::\w+)")

# dtest tests a dev-accepted removal relies on (`full` duplicates): not RED, their removal needs its own review
covers = {}  # (module, Class::test) → ["<module>::<test> (#<pr>)", ...]
decisions = {}  # (module, Class::test) → decision, unless reviewed
for f in sorted((ROOT / "analysis").glob("*.json")):
    for k, a in json.loads(f.read_text())["tests"].items():
        if not a.get("review"):
            decisions[f.stem, k] = a.get("decision")
        if a.get("review", {}).get("verdict") == "remove":
            for d in a["duplicates"]:
                if d["coverage"] == "full" and (m := DTEST_PATH.fullmatch(d["path"])):
                    covers.setdefault((m[1].replace("/", "."), m[2]), []).append(f"{f.stem}::{k} (#{a['review']['pr']})")

errors = 0
for mod in sys.argv[1:]:
    data = json.loads((ROOT / f"data/{mod}.json").read_text())
    tests = {f"{t['class']}::{t['name']}" for t in data["tests"]}
    full = json.loads((ROOT / f"analysis/{mod}.json").read_text())
    analysis = full["tests"]
    problems = [f"missing {k}" for k in ("dtest_rev", "scylla_rev") if k not in full]
    try:  # jira keys committed at HEAD must survive rewrites by the analyze subagents
        old = json.loads(subprocess.run(["git", "show", f"HEAD:analysis/{mod}.json"], cwd=ROOT, check=True,
                                        capture_output=True, text=True).stdout)["tests"]
    except (subprocess.CalledProcessError, KeyError, ValueError):
        old = {}
    problems += [f"{k}: jira {a['jira']} dropped" for k, a in old.items()
                 if a.get("jira") and not analysis.get(k, {}).get("jira")]
    problems += [f"{k}: review {a['review']['url']} dropped or changed" for k, a in old.items()  # dev verdicts are final
                 if a.get("review") and {f: analysis.get(k, {}).get("review", {}).get(f) for f in REVIEW_FINAL}
                 != {f: a["review"][f] for f in REVIEW_FINAL}]
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
        elif d and not any(d["sha"].startswith(c) for c in a.get("commits", {})):
            problems.append(f"{k}: deleting commit {d['sha'][:10]} not in commits (delta.py --apply adds it)")
        if "jira" in a and not re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", str(a["jira"])):
            problems.append(f"{k}: bad jira {a['jira']!r}")
        issues = a.get("issues", [])
        problems += [f"{k}: bad issue {i}" for i in issues
                     if i.get("tag") not in TAGS.get(i.get("kind"), ()) or not i.get("text")]
        if r := a.get("review"):
            if r.keys() - REVIEW_KEYS or not REVIEW_FINAL <= r.keys() or r.get("verdict") not in VERDICT:
                problems.append(f"{k}: bad review {r!r}")
            elif a.get("decision") not in (VERDICT[r["verdict"]], "DELETED"):
                problems.append(f"{k}: review {r['verdict']} but decision {a.get('decision')}")
        if a.get("decision") == "RED" and not a.get("review") and (c := covers.get((mod, k))):
            problems.append(f"{k}: RED but covers the reviewed removal of {', '.join(c)}: YELLOW")
        if a.get("decision") == "GREEN" and not a.get("review") and any(i.get("kind") == "bug" for i in issues):
            problems.append(f"{k}: GREEN with a bug issue")
    problems += [f"{cm}::{ck} (another module): RED but covers the reviewed removal of {', '.join(c)}: YELLOW"
                 for (cm, ck), c in covers.items() if cm != mod and decisions.get((cm, ck)) == "RED"
                 and any(x.startswith(f"{mod}::") for x in c)]
    left = len(tests - analysis.keys())
    print(f"{mod}: {len(tests) - left}/{len(tests)} analyzed{f', {left} left' if left else ''}"
          f"{f', {len(norun)} without runs' if norun else ''}")
    for p in problems:
        print(f"  {p}")
    errors += len(problems)
sys.exit(1 if errors else 0)
