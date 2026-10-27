#!/usr/bin/env python3
"""Generate per-file triage data (tests, Jenkins stats, git history, PRs) as JSON.

usage: gen_data.py [MODULE ...]   (default: all modules in jenkins/*_long.csv)
Reads jenkins/<job>_long.csv for each job, writes data/<module>.json + data/index.json.
"""
import ast
import csv
import json
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from functools import cache
from pathlib import Path

DTEST = Path("~/github/scylla-dtest").expanduser()
ROOT = Path(__file__).resolve().parent.parent
REV = "upstream/next"
REPO = "scylladb/scylla-dtest"
CACHE = ROOT / "cache" / "prs.json"
GITATTR = "/tmp/gitattr"
SEP = "\x1f"


def git(*args):
    return subprocess.run(["git", "-C", DTEST, "-c", f"core.attributesFile={GITATTR}", *args],
                          capture_output=True, text=True, check=True).stdout


def parse_log(out):
    commits = []
    for line in out.splitlines():
        if line.startswith("COMMIT" + SEP):
            _, sha, date, author, subject = line.split(SEP, 4)
            commits.append({"sha": sha, "date": date, "author": author, "subject": subject})
    return commits


LOG_FMT = f"--format=COMMIT{SEP}%H{SEP}%as{SEP}%an{SEP}%s"


@cache
def classes(path, rev=REV):
    """{class: (base names, {func: (start, end)})}, ranges incl. decorators."""
    out = {}
    for cls in ast.parse(git("show", f"{rev}:{path}")).body:
        if isinstance(cls, ast.ClassDef):
            funcs = {f.name: (min([f.lineno] + [d.lineno for d in f.decorator_list]), f.end_lineno)
                     for f in cls.body if isinstance(f, ast.FunctionDef)}
            out[cls.name] = ([ast.unparse(b).split(".")[-1] for b in cls.bases], funcs)
    return out


def locate(path, cls, func, rev=REV, anywhere=True):
    """(path, defining class, (start, end)): class, its bases in the file, else (`anywhere`) any class in the repo."""
    todo, seen = [cls], set()
    while todo:
        c = todo.pop(0)
        if c in seen or c not in classes(path, rev):
            continue
        seen.add(c)
        bases, funcs = classes(path, rev)[c]
        if func in funcs:
            return path, c, funcs[func]
        todo += bases
    if not anywhere:
        raise KeyError((path, cls, func))
    hits = subprocess.run(["git", "-C", DTEST, "grep", "-l", f"def {func}(", rev, "--", "*.py"],
                          capture_output=True, text=True).stdout
    for hit in hits.split():
        other = hit.split(":", 1)[1]
        for c, (_, funcs) in classes(other, rev).items():
            if func in funcs:
                return other, c, funcs[func]
    raise KeyError((path, cls, func))


def load_stats():
    """{module: {(class, func): {param_id: {job: [(build, status, dur)]}}}}; module is dotted (dir.file)."""
    stats = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list))))
    for long_csv in sorted((ROOT / "jenkins").glob("*_long.csv")):
        job = long_csv.name.removesuffix("_long.csv")
        for r in csv.DictReader(open(long_csv)):
            if r["status"] == "SKIPPED":
                continue
            base, bracket, param = r["test"].partition("[")
            base, at, variant = base.partition("@")  # e.g. test_x@high_memory
            mod, cls, func = base.rsplit(".", 2)
            stats[mod][(cls, func)][at + variant + bracket + param][job].append((int(r["build"]), r["status"], float(r["duration"])))
    return stats


def summarize(by_job):
    """Combined stats over all jobs + per-job breakdown."""
    out = _summarize([r for runs in by_job.values() for r in runs])
    out["by_job"] = {j: _summarize(r) for j, r in sorted(by_job.items())}
    return out


def _summarize(runs):
    passed = sum(s == "PASSED" for _, s, _ in runs)
    return {"runs": len(runs), "pass_rate": round(100 * passed / len(runs), 1),
            "avg_s": round(sum(d for *_, d in runs) / len(runs), 1)}


class PRs:
    def __init__(self):
        self.cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}

    def get(self, sha):
        if sha not in self.cache:
            out = subprocess.run(["gh", "api", f"repos/{REPO}/commits/{sha}/pulls",
                                  # skip pytest-port branch PRs and Cassandra upstream merges: not the origin
                                  "--jq", '[.[] | select(.base.ref == "next" or .base.ref == "master")'
                                          ' | select(.title | startswith("Merge upstream") | not)'
                                          ' | {number, title}][0]'],
                                 capture_output=True, text=True, check=True).stdout.strip()
            self.cache[sha] = json.loads(out) if out and out != "null" else None
        return self.cache[sha]

    def save(self):
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(self.cache, indent=1, sort_keys=True))


def with_prs(commits, prs):
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(prs.get, {c["sha"] for c in commits}))
    for c in commits:
        c["pr"] = prs.get(c["sha"])
    return commits


def main():
    mods = sys.argv[1:]
    Path(GITATTR).write_text("*.py diff=python\n")
    out_dir = ROOT / "data"
    out_dir.mkdir(exist_ok=True)
    stats = load_stats()
    prs = PRs()
    for mod in mods or sorted(stats):
        path = mod.replace(".", "/") + ".py"
        if not git("ls-tree", "--name-only", REV, "--", path).strip():
            print(f"skip {mod}: not in {REV}", file=sys.stderr)
            continue
        tests = []
        for (cls, func), params in sorted(stats[mod].items()):
            try:
                src, owner, (start, end) = locate(path, cls, func)
            except KeyError:
                print(f"skip {mod}.{cls}.{func}: not in {REV}", file=sys.stderr)
                continue
            commits = parse_log(git("log", REV, LOG_FMT, "--no-patch", "-L", f"{start},{end}:{src}"))
            all_runs = defaultdict(list)
            for by_job in params.values():
                for j, r in by_job.items():
                    all_runs[j] += r
            tests.append({
                "class": cls, "name": func, "lines": [start, end],
                **({"defined_in": f"{src}::{owner}"} if (src, owner) != (path, cls) else {}),
                "stats": summarize(all_runs),
                "params": {p: summarize(r) for p, r in sorted(params.items()) if p},
                "commits": with_prs(commits, prs),
            })
        file_commits = parse_log(git("log", REV, LOG_FMT, "--follow", "--", path))
        data = {"file": path, "rev": git("rev-parse", REV).strip(), "tests": tests,
                "file_commits": with_prs(file_commits, prs)}
        (out_dir / f"{mod}.json").write_text(json.dumps(data, indent=1))
        prs.save()
        index = sorted(p.stem for p in out_dir.glob("*.json") if p.name != "index.json")
        (out_dir / "index.json").write_text(json.dumps(index, indent=1))
        print(f"{mod}: {len(tests)} tests, {len(file_commits)} file commits", file=sys.stderr)


if __name__ == "__main__":
    main()
