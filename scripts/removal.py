#!/usr/bin/env python3
"""Helpers for dtest removal PRs (/remove-tests skill). TEST = <module>::<Class>::<test>.

usage: removal.py select [--module GLOB]... [--decision D]... [--kind K]... [--dup-repo R]... [--group G]...
       removal.py info TEST... | -          (fetch dtest next, scylladb/scylla-manager master first)
       removal.py strip [--force] TARGET... (in a dtest worktree)
       removal.py collect-diff [--base REV] TEST...  (in a dtest worktree)

select: `<test>  <decision>  <kind>  jira=<key>  pending=<branch>  dup=<first full duplicate>`, DELETED never listed.
  --decision default RED. --module matches the dotted module or its file path (fnmatch).
  --dup-repo: repo of a full duplicate: scylla | manager | dtest | other (unparsed path).
  kind: covered      full duplicate, no `bug` issue
        covered-bug  full duplicate and a `bug` issue: removed for coverage but buggy, its own PR
        bug          `bug` issue, no full duplicate
        other        neither: feature removed, low value, Cassandra-only... (read `reason`)
  pending: an unmerged local/origin dtest branch deletes `def <test>` in that file.
info: commit material per test (markdown) + check of each full duplicate at the latest upstream:
  ok           file + test (+ go subtest) exist; permalink
  missing      file or test gone
  unverified   path doesn't parse (free text, globs, whole file, other repo), class-only, or subtest not found
  dup-red / dup-selected / dup-pending: a dtest duplicate that is RED/DELETED, in this selection, or removed on
               a pending branch; doesn't count as coverage
  covered/covered-bug tests without an `ok` duplicate are BLOCKED (exit 1). Header: `Closes:` = Jira keys whose
  every test is in the selection.
strip: remove functions/classes (with decorators and the comments right above) from a dtest worktree.
  TARGET = <path.py>::<Class>::<name> | <path.py>::<name> | <module>::<Class>::<test> (at its `defined_in`).
  Then: drop the imports this made unused, ruff isort + format, fail on new pyflakes issues, fail if a removed
  non-test name is still referenced anywhere (--force: other same-named defs), warn on references to a removed test,
  list candidates: names the removed code used whose definitions now have no references.
collect-diff: pytest --collect-only of the whole repo at --base (default merge-base with upstream/next) and of the
  working tree; exit 1 unless exactly the given tests disappeared (inherited copies, added tests, new collection
  errors all fail).
"""
import argparse
import ast
import builtins
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import date
from fnmatch import fnmatchcase
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GH = Path.home() / "github"
DTEST = GH / "scylla-dtest"
NEXT = "upstream/next"
REPOS = {"scylla": (GH / "scylladb", "upstream/master", "scylladb"),
         "manager": (GH / "scylla-manager", "upstream/master", "scylla-manager"),
         "dtest": (DTEST, NEXT, "scylla-dtest")}
SKIP_NAMES = set(dir(builtins)) | {"self", "cls"}


def git_try(repo, *args) -> str | None:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return None if r.returncode else r.stdout


def git(repo, *args) -> str:
    out = git_try(repo, *args)
    if out is None:
        sys.exit(f"git -C {repo} {' '.join(args)} failed")
    return out


def run(cmd, cwd, inp=None):
    return subprocess.run([str(c) for c in cmd], cwd=cwd, input=inp, capture_output=True, text=True)


@cache
def sha(repo):
    rdir, rev, _ = REPOS[repo]
    return git(rdir, "rev-parse", rev).strip()


# --- triage data -------------------------------------------------------------------------------------------------

@cache
def analysis():
    return {f.stem: json.loads(f.read_text())["tests"] for f in (ROOT / "analysis").glob("*.json")}


@cache
def data(mod):
    f = ROOT / f"data/{mod}.json"
    if not f.exists():
        return {"file": mod.replace(".", "/") + ".py", "tests": {}}
    d = json.loads(f.read_text())
    return {"file": d["file"], "tests": {f"{t['class']}::{t['name']}": t for t in d["tests"]}}


def split_test(t):
    mod, key = t.split("::", 1)
    if mod not in analysis() or key not in analysis()[mod]:
        sys.exit(f"not in analysis: {t}")
    return mod, key


def location(mod, key):
    """(path, class) where the test function is defined."""
    t = data(mod)["tests"].get(key, {})
    if t.get("defined_in"):
        path, cls = t["defined_in"].split("::")
        return path, cls
    return data(mod)["file"], key.split("::")[0]


def kind(e):
    full = any(d["coverage"] == "full" for d in e.get("duplicates", []))
    bug = any(i["kind"] == "bug" for i in e.get("issues", []))
    return ("covered-bug" if bug else "covered") if full else ("bug" if bug else "other")


def full_dups(e):
    return [d for d in e.get("duplicates", []) if d["coverage"] == "full"]


@cache
def pending():
    """{(file, test name): branch} for `def test_*` removed (not re-added) on unmerged local/origin branches."""
    out = {}
    refs = git(DTEST, "for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes/origin").split()
    for ref in refs:
        if ref == "origin" or ref.endswith("/HEAD") or git_try(DTEST, "merge-base", "--is-ancestor", ref, NEXT) is not None:
            continue
        diff = git_try(DTEST, "diff", "-U0", f"{NEXT}...{ref}", "--", "*.py") or ""
        removed, added, f = set(), set(), None
        for line in diff.splitlines():
            if line.startswith("diff --git "):
                f = line.split(" b/", 1)[1]
            elif m := re.match(r"([-+])\s*(?:async\s+)?def (test_\w+)\(", line):
                (removed if m[1] == "-" else added).add((f, m[2]))
        for k in removed - added:
            out.setdefault(k, ref)
    return out


def pending_of(mod, key):
    path, _ = location(mod, key)
    return pending().get((path, key.split("::")[-1]))


# --- duplicate verification --------------------------------------------------------------------------------------

def parse_dup(p):
    """(repo, file, class, func, go subtest); func None = not checkable. None = unparsed."""
    p = p.strip()
    if m := re.match(r"scylla-manager@\S+\s+(.*)", p):
        repo, rest = "manager", m[1]
    elif p.startswith("test/"):
        repo, rest = "scylla", p
    elif m := re.match(r"(?:scylla-)?dtest\s+(.*)", p):
        repo, rest = "dtest", m[1]
    elif re.match(r"[\w/]+\.py\b", p):
        repo, rest = "dtest", p
    else:
        return None
    m = re.match(r"([\w./-]+\.\w+)(?:::([^(,;]*))?", rest)
    if not m:
        return None
    file, names = m[1], re.sub(r"\[[^\]]*\]", "", m[2] or "").strip()
    if file.endswith(".go"):
        func, _, sub = names.partition("/")
        func = func.strip()
        return repo, file, None, func if re.fullmatch(r"\w+", func) else None, sub.strip() or None
    parts = names.split("::")
    if not names or re.search(r"[*/\s]", names) or not re.fullmatch(r"[a-z_]\w*", parts[-1]):
        return repo, file, None, None, None
    return repo, file, parts[0] if len(parts) > 1 else None, parts[-1], None


def find_line(src, file, cls, func, sub):
    """(1-based line, None) or (None, status)."""
    lines = src.splitlines()
    ext = file.rsplit(".", 1)[-1]
    if ext == "py":
        lo, hi = 0, len(lines)
        if cls:
            lo = next((i for i, l in enumerate(lines) if re.match(rf"class {cls}\b", l)), None)
            if lo is None:
                return None, "missing"
            hi = next((i for i in range(lo + 1, len(lines)) if re.match(r"(@|class |def |async def )", lines[i])), hi)
        i = next((i for i in range(lo, hi) if re.match(rf"\s*(async\s+)?def {func}\(", lines[i])), None)
        return (i + 1, None) if i is not None else (None, "unverified" if cls else "missing")
    if ext == "go":
        i = next((i for i, l in enumerate(lines) if re.match(rf"func {func}\(", l)), None)
        if i is None:
            return None, "missing"
        if sub:
            i = next((j for j in range(i, len(lines)) if f'"{sub}"' in lines[j] or f"`{sub}`" in lines[j]), None)
            if i is None:
                return None, "unverified"
        return i + 1, None
    if ext in ("cc", "hh"):
        i = next((i for i, l in enumerate(lines) if "TEST_CASE(" in l and re.search(rf"\b{func}\b", l)), None)
        return (i + 1, None) if i is not None else (None, "missing")
    return None, "unverified"


def verify(path, sel):
    """(status, permalink, detail)."""
    p = parse_dup(path)
    if not p:
        return "unverified", None, "unparsed path"
    repo, file, cls, func, sub = p
    if not func:
        return "unverified", None, "whole file, glob, several tests or class only"
    rdir, rev, name = REPOS[repo]
    src = git_try(rdir, "show", f"{rev}:{file}")
    if src is None:
        return "missing", None, f"{file} not at {rev}"
    line, status = find_line(src, file, cls, func, sub)
    if status:
        return status, None, f"{'subtest ' + repr(sub) if sub and status == 'unverified' else func} not found at {rev}"
    link = f"https://github.com/scylladb/{name}/blob/{sha(repo)}/{file}#L{line}"
    if repo == "dtest":
        mod = file[:-3].replace("/", ".")
        tests = analysis().get(mod, {})
        keys = [k for k in tests if (k == f"{cls}::{func}" if cls else k.endswith(f"::{func}"))]
        if any(f"{mod}::{k}" in sel for k in keys):
            return "dup-selected", link, "also in this selection"
        if bad := [k for k in keys if tests[k]["decision"] in ("RED", "DELETED")]:
            return "dup-red", link, f"{mod}::{bad[0]} is {tests[bad[0]]['decision']}"
        if br := pending().get((file, func)):
            return "dup-pending", link, f"removed on branch {br}"
    return "ok", link, ""


def dup_repo(path):
    p = parse_dup(path)
    return p[0] if p else "other"


# --- commands ----------------------------------------------------------------------------------------------------

def cmd_select(a):
    sys.path.insert(0, str(ROOT / "scripts"))
    from groups import group_of  # noqa: PLC0415

    counts = Counter()
    for mod, tests in sorted(analysis().items()):
        if a.module and not any(fnmatchcase(mod, g) or fnmatchcase(data(mod)["file"], g) for g in a.module):
            continue
        for key, e in sorted(tests.items()):
            k, dups = kind(e), full_dups(e)
            if (e["decision"] == "DELETED" or e["decision"] not in a.decision or (a.kind and k not in a.kind)
                    or (a.dup_repo and not any(dup_repo(d["path"]) in a.dup_repo for d in dups))
                    or (a.group and group_of(mod, key) not in a.group)):
                continue
            counts[k] += 1
            dup = dups[0]["path"][:100] if dups else "-"
            print(f"{mod}::{key}  {e['decision']}  {k}  jira={e.get('jira', '-')}  "
                  f"pending={pending_of(mod, key) or '-'}  dup={dup}")
    print(f"# {sum(counts.values())} tests: " + ", ".join(f"{k} {n}" for k, n in sorted(counts.items())),
          file=sys.stderr)


def cmd_info(a):
    tests = sys.stdin.read().split() if a.tests == ["-"] else a.tests
    sel = set(tests)
    out, blocked = [], []
    for t in tests:
        mod, key = split_test(t)
        e = analysis()[mod][key]
        path, cls = location(mod, key)
        dt = data(mod)["tests"].get(key, {})
        st = dt.get("stats")
        runs = (f"{st['runs']} runs, {st['pass_rate']:g}% pass, avg {st['avg_s']:.0f}s" if st and st.get("runs")
                else "no runs recorded")
        inh = f" (inherited from `{dt['defined_in']}`)" if dt.get("defined_in") else ""
        k = kind(e)
        out += [f"### {t}",
                f"- dtest: `{path}::{cls}::{key.split('::')[-1]}`{inh} · {e['decision']} · {k} · "
                f"jira {e.get('jira', '-')} · {runs}",
                f"- reason: {e['reason']}"]
        if br := pending_of(mod, key):
            out.append(f"- PENDING: already removed on branch {br}")
        for i in e.get("issues", []):
            out.append(f"- {i['kind']} {i['tag']} `{i['ref']}`: {i['text']}")
        ok = False
        if dups := full_dups(e):
            out.append("- full duplicates:")
        for d in dups:
            status, link, detail = verify(d["path"], sel)
            ok |= status == "ok"
            out.append(f"  - {status} `{d['path']}`" + (f" {link}" if link else "") + (f" ({detail})" if detail else ""))
            out.append(f"    note: {d.get('note', '')}")
        if k.startswith("covered") and not ok:
            blocked.append(t)
            out.append("- status: BLOCKED (no `ok` full duplicate: check `unverified` ones by hand, or drop the test)")
        out.append("")
    keys = {analysis()[m][k].get("jira") for m, k in map(split_test, tests)} - {None}
    closes = sorted(j for j in keys if all(f"{m}::{k}" in sel for m, ts in analysis().items()
                                           for k, e in ts.items() if e.get("jira") == j))
    kinds = Counter(kind(analysis()[m][k]) for m, k in map(split_test, tests))
    print(f"# Removal material {date.today()}: dtest {NEXT} {sha('dtest')[:10]}, scylladb {sha('scylla')[:10]}, "
          f"scylla-manager {sha('manager')[:10]}")
    print(f"Tests: {len(tests)} ({', '.join(f'{k} {n}' for k, n in sorted(kinds.items()))}); "
          f"blocked: {', '.join(blocked) or 'none'}")
    print(f"Closes: {', '.join(closes) or 'none'}" + (f"; other Jira keys (left to jira_sync): "
                                                      f"{', '.join(sorted(keys - set(closes)))}" if keys - set(closes) else ""))
    print()
    print("\n".join(out))
    sys.exit(1 if blocked else 0)


def toplevel():
    repo = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    if not (repo / "dtest_class.py").exists():
        sys.exit("run inside a scylla-dtest worktree")
    return repo


def venv():
    b = DTEST / f".venv-dtest-{(DTEST / '.python-version').read_text().strip()}" / "bin"
    for tool in ("ruff", "python"):
        if not (b / tool).exists():
            sys.exit(f"missing {b / tool}")
    return b


def flakes(ruff, repo, path, src):
    r = run([ruff, "check", "--select", "F", "--output-format", "json", "--stdin-filename", path, "-"], repo, src)
    if r.returncode not in (0, 1):
        sys.exit(f"ruff failed on {path}: {r.stderr}")
    return Counter((d["code"], d["message"]) for d in json.loads(r.stdout or "[]"))


def remove_defs(src, quals):
    """Source without the given defs ("Class.name" / "name"), and the names the removed code uses."""
    tree = ast.parse(src)
    defs = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    nodes = {}
    for n in tree.body:
        if isinstance(n, defs):
            nodes[n.name] = n
        if isinstance(n, ast.ClassDef):
            nodes |= {f"{n.name}.{s.name}": s for s in n.body if isinstance(s, defs)}
    lines = src.splitlines(keepends=True)
    spans, used = [], set()
    for q in quals:
        if q not in nodes:
            sys.exit(f"not defined: {q}")
        n = nodes[q]
        start = min([n.lineno] + [d.lineno for d in n.decorator_list]) - 1
        while start and lines[start - 1].lstrip().startswith("#"):
            start -= 1
        spans.append((start, n.end_lineno))
        for x in ast.walk(n):
            used |= ({x.id} if isinstance(x, ast.Name) else {x.attr} if isinstance(x, ast.Attribute)
                     else {x.arg} if isinstance(x, ast.arg) else set())
    for start, end in sorted(spans, reverse=True):
        del lines[start:end]
    return "".join(lines), used


def drop_imports(src, quals):
    """Remove the given qualified names (as ruff reports them) from top-level imports, keeping the layout."""
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    edits = []
    for n in tree.body:
        if not isinstance(n, (ast.Import, ast.ImportFrom)):
            continue
        mod = "." * getattr(n, "level", 0) + (getattr(n, "module", None) or "")

        def qual(x, n=n, mod=mod):
            return x.name if isinstance(n, ast.Import) else f"{mod}.{x.name}" if n.module else f"{mod}{x.name}"

        keep = [x for x in n.names if qual(x) not in quals]
        if len(keep) == len(n.names):
            continue
        parts = [f"{x.name} as {x.asname}" if x.asname else x.name for x in keep]
        if not keep:
            text = ""
        elif isinstance(n, ast.Import):
            text = f"import {', '.join(parts)}\n"
        elif (n.end_lineno or n.lineno) > n.lineno:
            text = f"from {mod} import (\n" + "".join(f"    {p},\n" for p in parts) + ")\n"
        else:
            text = f"from {mod} import {', '.join(parts)}\n"
        edits.append((n.lineno - 1, n.end_lineno, text))
    for start, end, text in sorted(edits, reverse=True):
        lines[start:end] = [text]
    return "".join(lines)


def grep_w(repo, name):
    out = git_try(repo, "grep", "-nw", "-e", name) or ""
    return out.splitlines()


def is_def(hit, name):
    text = hit.split(":", 2)[-1]
    return bool(re.match(rf"\s*(async\s+)?(def|class)\s+{name}\b", text) or re.match(rf"{name}\s*[:=]", text))


def resolve_target(t):
    """(path, "Class.name" | "name")."""
    parts = t.split("::")
    if parts[0].endswith(".py"):
        return parts[0], ".".join(parts[1:])
    mod, key = split_test(t)
    path, cls = location(mod, key)
    return path, f"{cls}.{key.split('::')[-1]}"


def cmd_strip(a):
    repo, b = toplevel(), venv()
    ruff = b / "ruff"
    by_file = defaultdict(list)
    for t in a.targets:
        path, q = resolve_target(t)
        by_file[path].append(q)
    backup, used, names, problems = {}, set(), set(), []

    def restore(msg):
        for f, src in backup.items():
            f.write_text(src)
        sys.exit(f"{msg}\nnothing changed")

    for path, quals in by_file.items():
        f = repo / path
        backup[f] = src = f.read_text()
        base = flakes(ruff, repo, path, src)
        new, u = remove_defs(src, quals)
        try:
            ast.parse(new)
        except SyntaxError as err:
            restore(f"{path}: broken after removal ({err}); a class left empty? strip the class instead")
        used |= u
        names |= {q.split(".")[-1] for q in quals}
        f.write_text(new)
        print(f"removed: {', '.join(f'{path}::{q}' for q in quals)}")
        added = flakes(ruff, repo, path, new) - base
        unused = [m[1] for c, msg in added if c == "F401" and (m := re.match(r"`([^`]+)` imported but unused", msg))]
        if unused:
            f.write_text(drop_imports(new, set(unused)))
            print(f"  imports removed: {', '.join(unused)}")
        r = run([ruff, "check", "--select", "I", "--fix", "-q", path], repo)
        if r.returncode:
            problems.append(f"{path}: isort: {r.stdout.strip()}")
        r = run([ruff, "format", "-q", path], repo)
        if r.returncode:
            restore(f"{path}: ruff format failed: {r.stderr.strip()}")
        problems += [f"{path}: {c} {msg}" for c, msg in flakes(ruff, repo, path, f.read_text()) - base]

    for name in sorted(names):
        refs = [h for h in grep_w(repo, name) if not is_def(h, name)]
        if not refs:
            continue
        shown = "\n    ".join(refs[:10])
        if name.startswith("test"):
            print(f"  warning: {name} still referenced:\n    {shown}")
        elif not a.force:
            restore(f"{name} still referenced (other same-named def? rerun with --force):\n    {shown}")
    cands = []
    for name in sorted(used - names - SKIP_NAMES):
        hits = grep_w(repo, name)
        defs = [h for h in hits if is_def(h, name)]
        if defs and len(defs) == len(hits):
            cands.append(f"{name}  {':'.join(defs[0].split(':', 2)[:2])}")
    if cands:
        print("candidates (defined, no references left):\n  " + "\n  ".join(cands))
    if problems:
        sys.exit("NEW ISSUES (fix, or `git checkout -- <file>` to undo):\n  " + "\n  ".join(problems))


def collect(py, tree):
    r = run([py, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "--continue-on-collection-errors"],
            tree)
    items, errors = Counter(), set()
    for line in r.stdout.splitlines():
        if line.startswith("ERROR "):
            errors.add(line)
        elif re.fullmatch(r"[\w/.-]+\.py::\S+", line):
            items[re.sub(r"\[.*", "", line)] += 1
    if not items:
        sys.exit(f"collection failed in {tree}:\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}")
    return items, errors


def cmd_collect_diff(a):
    repo, py = toplevel(), venv() / "python"
    base = a.base or git(repo, "merge-base", "HEAD", NEXT).strip()
    tmp = tempfile.mkdtemp(prefix="dtest-collect-", dir="/tmp")
    git(repo, "worktree", "add", "-q", "--detach", tmp, base)
    try:
        b_items, b_err = collect(py, tmp)
    finally:
        git_try(repo, "worktree", "remove", "--force", tmp)
        shutil.rmtree(tmp, ignore_errors=True)
    h_items, h_err = collect(py, repo)
    expected = set()
    for t in a.tests:
        parts = t.split("::")
        expected.add(t if parts[0].endswith(".py") else f"{data(parts[0])['file']}::{'::'.join(parts[1:])}")
    removed, added = set(b_items) - set(h_items), set(h_items) - set(b_items)
    bad = [f"UNEXPECTED removed: {x}" for x in sorted(removed - expected)]
    bad += [f"NOT removed: {x}" for x in sorted(expected - removed) if x in b_items]
    bad += [f"ADDED: {x}" for x in sorted(added)]
    bad += [f"new collection error: {x}" for x in sorted(h_err - b_err)]
    for x in sorted(expected - removed - set(b_items)):
        print(f"warning: not collected at base {base[:10]} (deselected or missing): {x}")
    print(f"base {base[:10]}: {sum(b_items.values())} items; removed {len(removed)} tests "
          f"({sum(b_items[x] for x in removed)} items)")
    if bad:
        sys.exit("\n".join(bad))
    print("OK: exactly the expected tests disappeared")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select")
    s.add_argument("--module", action="append")
    s.add_argument("--decision", action="append")
    s.add_argument("--kind", action="append", choices=["covered", "covered-bug", "bug", "other"])
    s.add_argument("--dup-repo", action="append", choices=["scylla", "manager", "dtest", "other"])
    s.add_argument("--group", action="append")
    sub.add_parser("info").add_argument("tests", nargs="+")
    s = sub.add_parser("strip")
    s.add_argument("--force", action="store_true")
    s.add_argument("targets", nargs="+")
    s = sub.add_parser("collect-diff")
    s.add_argument("--base")
    s.add_argument("tests", nargs="+")
    a = p.parse_args()
    if a.cmd == "select":
        a.decision = a.decision or ["RED"]
    {"select": cmd_select, "info": cmd_info, "strip": cmd_strip, "collect-diff": cmd_collect_diff}[a.cmd](a)


if __name__ == "__main__":
    main()
