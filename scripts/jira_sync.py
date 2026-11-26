#!/usr/bin/env python3
"""Close Jira issues whose tests are gone or no longer RED, then parents once all their sub-tasks are done.

usage: jira_sync.py [--apply] [--note TEXT] [KEY ...]
  dry run without --apply; KEYs: only those issues, no parents; --note (needs KEYs): appended to the comment

Per `jira` key (all tests carrying it): all DELETED → Done; all GREEN or DELETED → Won't Fix (the test stays; a dev
review that said keep makes it GREEN); YELLOW keeps the issue open (still needs an opinion); parent with all sub-tasks done → Done. Output: `<key> CLOSE <status>: <why>`, `<key> SKIP <why>` for keys
with a changed test that stay open. REST via `curl -n` (Python's netrc needs 0600).
"""
import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://scylladb.atlassian.net/rest/api/2"
DTEST = "https://github.com/scylladb/scylla-dtest"
ap = argparse.ArgumentParser(usage=__doc__.split("usage: ")[1].split("\n\n")[0])
ap.add_argument("--apply", action="store_true")
ap.add_argument("--note")
ap.add_argument("keys", nargs="*")
args = ap.parse_args()
apply, only, note = args.apply, set(args.keys), args.note
if note and not only:
    ap.error("--note needs KEYs")


def jira(method, path, body=None):
    out = subprocess.run(["curl", "-n", "-sS", "-f", "-X", method, "-H", "Content-Type: application/json",
                          f"{API}/{path}"] + (["-d", "@-"] if body else []),
                         input=json.dumps(body) if body else None, capture_output=True, text=True)
    if out.returncode:
        sys.exit(f"jira {method} {path}: {out.stderr.strip()} (auth error → fix ~/.netrc)")
    return json.loads(out.stdout) if out.stdout.strip() else {}


def search(jql):
    issues, token = [], None
    while True:
        r = jira("POST", "search/jql", {"jql": jql, "fields": ["status", "parent", "issuetype", "labels"], "maxResults": 100,
                                        **({"nextPageToken": token} if token else {})})
        issues += r["issues"]
        if not (token := r.get("nextPageToken")):
            return {i["key"]: i["fields"] for i in issues}


def fetch(keys, field="key"):
    keys, out = sorted(keys), {}
    for i in range(0, len(keys), 100):
        out |= search(f"{field} in ({', '.join(keys[i:i + 100])})")
    return out


def done(f):
    return f["status"]["statusCategory"]["key"] == "done"


def close(key, why, status="Done"):
    why += f"\n\n{note}" if note else ""
    print(f"{key} CLOSE {status}: {why}")
    if apply:
        transitions = jira("GET", f"issue/{key}/transitions")["transitions"]
        if not (tid := next((t["id"] for t in transitions if t["to"]["name"] == status), None)):
            sys.exit(f"{key}: no transition to {status}")
        jira("POST", f"issue/{key}/comment", {"body": f"dtest triage: {why}"})
        jira("POST", f"issue/{key}/transitions", {"transition": {"id": tid}})


tests = defaultdict(list)  # jira key → [(module::test, analysis entry)]
for f in sorted((ROOT / "analysis").glob("*.json")):
    for k, a in json.loads(f.read_text())["tests"].items():
        if a.get("jira") and (not only or a["jira"] in only):
            tests[a["jira"]].append((f"{f.stem}::{k}", a))
if only - tests.keys():
    sys.exit(f"not a `jira` of any test: {' '.join(sorted(only - tests.keys()))}")
if not tests:
    sys.exit()
issues = fetch(tests)
closed = set()
for key, ts in sorted(tests.items()):
    if key not in issues or done(issues[key]):
        continue
    why = "; ".join(f"{t} deleted from scylla-dtest in {d['sha'][:10]} ({DTEST}/commit/{d['sha']}"
                    f"{f', {DTEST}/pull/' + str(d['pr']) if d['pr'] else ''}) on {d['date']}"
                    if (d := a.get("deleted")) else f"{t} is now {a['decision']}: {a['reason']}"
                    for t, a in ts if a["decision"] != "RED")
    if all(a["decision"] == "DELETED" for _, a in ts):
        close(key, why)
    elif all(a["decision"] in ("GREEN", "DELETED") for _, a in ts):
        close(key, why, "Won't Fix")
    elif any(a["decision"] != "RED" for _, a in ts):
        print(f"{key} SKIP still on {', '.join(t for t, a in ts if a['decision'] != 'DELETED')}")
        continue
    else:
        continue
    closed.add(key)

if only:
    sys.exit()
parents = {f["parent"]["key"] for f in issues.values() if f["issuetype"]["subtask"]}
children = defaultdict(list)
for k, f in fetch(parents, "parent").items():
    children[f["parent"]["key"]].append(done(f) or k in closed)
for key, f in sorted(fetch(parents).items()):
    if not done(f) and children[key] and all(children[key]):
        close(key, f"all {len(children[key])} sub-tasks are done")
