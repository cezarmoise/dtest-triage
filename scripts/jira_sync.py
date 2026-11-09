#!/usr/bin/env python3
"""Close Jira issues whose tests are gone or no longer RED, then parents once all their sub-tasks are done.

usage: jira_sync.py [--apply]   (dry run without --apply)

Per `jira` key (all tests carrying it): all DELETED → Done; `dtest-red` issue and none RED → Won't Fix (the test
stays); parent with all sub-tasks done → Done. Output: `<key> CLOSE <status>: <why>`, `<key> SKIP <why>` for keys
with a changed test that stay open. REST via `curl -n` (Python's netrc needs 0600).
"""
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://scylladb.atlassian.net/rest/api/2"
DTEST = "https://github.com/scylladb/scylla-dtest"
apply = "--apply" in sys.argv[1:]


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
        if a.get("jira"):
            tests[a["jira"]].append((f"{f.stem}::{k}", a))
if not tests:
    sys.exit()
issues = fetch(tests)
closed = set()
for key, ts in sorted(tests.items()):
    if key not in issues or done(issues[key]):
        continue
    red = [t for t, a in ts if a["decision"] == "RED"]
    why = "; ".join(f"{t} deleted from scylla-dtest in {d['sha'][:10]} ({DTEST}/commit/{d['sha']}"
                    f"{f', {DTEST}/pull/' + str(d['pr']) if d['pr'] else ''}) on {d['date']}"
                    if (d := a.get("deleted")) else f"{t} is now {a['decision']}: {a['reason']}"
                    for t, a in ts if a["decision"] != "RED")
    if all(a["decision"] == "DELETED" for _, a in ts):
        close(key, why)
    elif "dtest-red" in issues[key]["labels"] and not red:
        close(key, why, "Won't Fix")
    elif any(a["decision"] == "DELETED" for _, a in ts) or "dtest-red" in issues[key]["labels"] and len(red) < len(ts):
        print(f"{key} SKIP still on {', '.join(t for t, a in ts if a['decision'] != 'DELETED')}")
        continue
    else:
        continue
    closed.add(key)

parents = {f["parent"]["key"] for f in issues.values() if f["issuetype"]["subtask"]}
children = defaultdict(list)
for k, f in fetch(parents, "parent").items():
    children[f["parent"]["key"]].append(done(f) or k in closed)
for key, f in sorted(fetch(parents).items()):
    if not done(f) and children[key] and all(children[key]):
        close(key, f"all {len(children[key])} sub-tasks are done")
