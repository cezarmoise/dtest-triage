#!/usr/bin/env python3
"""List analyzed tests to recheck: dtest changes since each module's `dtest_rev`, closed issues from
`open-issue` notes, scylla commits porting dtests since `scylla_rev`.

usage: delta.py [--apply] [MODULE ...]              report (default: every analysis/*.json)
       delta.py --bump DTEST_REV SCYLLA_REV MODULE ...
--apply: write DELETED tests; bump revs of modules with nothing else to recheck.
--bump:  set revs after a module's recheck (use the revs from the report header).

Output: header `# dtest_rev <sha> scylla_rev <sha>`, then `<module> <Class::test> <KIND> <detail>`:
  DELETED  gone at upstream/next; detail = deleting commit
  MOVED    gone, but its file was renamed, same name is in another file, or renamed by the deleting commit;
           detail = file::Class::test
  CHANGED  test code changed (AST compare: formatting and reverted changes don't count); detail = commits
  HELPER   class, fixture, helper or constant it reaches (within its imports) changed; detail = file:name
  ISSUE    issue of an `open-issue` note is closed; detail = issues
  PORTED   scylla commit mentioning dtest adds a same-named test, or names the module and the test;
           detail = sha path::test. Key `*`: names the module but none of its tests.
"""
import ast
import copy
import difflib
import json
import re
import subprocess
import sys
import warnings
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from functools import cache
from pathlib import Path

from gen_data import LOG_FMT, REV, ROOT, PRs, classes, git, locate, parse_log

SCYLLA = Path("~/github/scylladb").expanduser()
SCYLLA_REV = "upstream/master"
FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
SETUP = {"setUp", "tearDown", "setup_method", "teardown_method", "setup_class", "teardown_class"}
IDENT = re.compile(r"[A-Za-z_]\w*\Z")
ISSUE = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/(?:issues|pull)/(\d+)|(?<![\w#])(?:([\w.-]+/[\w.-]+)|([\w.-]+))?#(\d+)")
warnings.filterwarnings("ignore", category=SyntaxWarning)  # invalid escapes in old dtest code
REPOS = {"": "scylladb/scylladb", "scylla": "scylladb/scylladb", "dtest": "scylladb/scylla-dtest"}  # else scylladb/<name>


def load(mod):
    return json.loads((ROOT / f"analysis/{mod}.json").read_text())


def save(mod, a):
    (ROOT / f"analysis/{mod}.json").write_text(json.dumps(a, indent=2, ensure_ascii=False) + "\n")


def scylla(*args):
    return subprocess.run(["git", "-C", SCYLLA, *args], capture_output=True, text=True, check=True).stdout


@cache
def files(rev):
    return set(git("ls-tree", "-r", "--name-only", rev).splitlines())


@cache
def tree(path, rev):
    return ast.parse(git("show", f"{rev}:{path}")) if path in files(rev) else None


@cache
def defs(path, rev):
    """{qualname: node}: module-level functions, classes (without methods), assignments; methods as Class.name."""
    out = {}
    for n in tree(path, rev).body if tree(path, rev) else []:
        if isinstance(n, FUNCS):
            out[n.name] = n
        elif isinstance(n, ast.ClassDef):
            out[n.name] = copy.copy(n)
            out[n.name].body = [s for s in n.body if not isinstance(s, FUNCS)]
            out |= {f"{n.name}.{f.name}": f for f in n.body if isinstance(f, FUNCS)}
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            out |= {x.id: n for t in targets for x in ast.walk(t) if isinstance(x, ast.Name)}
    return out


@cache
def changed(base):
    """(files, {(file, qualname)} of non-test defs) that differ between base and REV."""
    paths = frozenset(git("diff", "--name-only", base, REV, "--", "*.py").split())
    out = set()
    for f in paths:
        old, new = defs(f, base), defs(f, REV)
        out |= {(f, q) for q in old.keys() | new.keys() if not q.rsplit(".", 1)[-1].startswith("test")
                and (q not in old or q not in new or ast.dump(old[q]) != ast.dump(new[q]))}
    return paths, out


@cache
def refs(path, q):
    """Names a def uses: names, attributes, args (fixtures), identifier strings (usefixtures, getattr)."""
    out = set()
    for x in ast.walk(defs(path, REV)[q]):
        if isinstance(x, ast.Name):
            out.add(x.id)
        elif isinstance(x, ast.Attribute):
            out.add(x.attr)
        elif isinstance(x, ast.arg):
            out.add(x.arg)
        elif isinstance(x, ast.Constant) and isinstance(x.value, str) and IDENT.match(x.value):
            out.add(x.value)
    return out


def implicit(node):
    """Runs without being referenced: setup/teardown methods, autouse fixtures."""
    return isinstance(node, FUNCS) and (node.name in SETUP or any(
        isinstance(k, ast.keyword) and k.arg == "autouse" for d in node.decorator_list for k in ast.walk(d)))


@cache
def imports(path):
    """Repo files imported by `path` (absolute imports only)."""
    out = set()
    for n in ast.walk(tree(path, REV)):
        if isinstance(n, ast.Import):
            mods = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            mods = [n.module] + [f"{n.module}.{a.name}" for a in n.names]
        else:
            continue
        for m in mods:
            p = m.replace(".", "/")
            out |= {f for f in (f"{p}.py", f"{p}/__init__.py") if f in files(REV)}
    return out


@cache
def scope(*roots):
    """roots, their transitive imports and conftest.py files."""
    todo, seen = list(roots), set()
    for r in roots:
        parts = r.split("/")[:-1]
        todo += [f for i in range(len(parts) + 1) if (f := "/".join(parts[:i] + ["conftest.py"])) in files(REV)]
    while todo:
        if (p := todo.pop()) not in seen:
            seen.add(p)
            todo += imports(p)
    return frozenset(seen)


@cache
def index(*roots):
    """{short name: [(file, qualname)]} over scope(roots)."""
    out = defaultdict(list)
    for f in scope(*roots):
        for q in defs(f, REV):
            out[q.rsplit(".", 1)[-1]].append((f, q))
    return out


def reach(path, cls, src, owner, func):
    """(file, qualname) defs the test can use, by name (over-approximates)."""
    idx = index(path, src)
    todo = [(src, f"{owner}.{func}"), (src, owner), (path, cls)]
    todo += [(path, q) for q, n in defs(path, REV).items() if "." not in q and implicit(n)]
    out, names = set(), set()
    while todo:
        f, q = todo.pop()
        if (f, q) in out or q not in defs(f, REV):
            continue
        out.add((f, q))
        if isinstance(defs(f, REV)[q], ast.ClassDef):
            todo += [(f, m) for m, n in defs(f, REV).items() if m.startswith(q + ".") and implicit(n)]
        for n in refs(f, q) - names:
            names.add(n)
            todo += idx.get(n, [])
    return out


def find(path, cls, func, rev, fallback=None):
    """(src, owner) of the test at rev, or None. fallback = (src, owner) where it was defined before."""
    if path in files(rev):
        try:
            src, owner, _ = locate(path, cls, func, rev, anywhere=fallback is None)
            return src, owner
        except KeyError:
            pass
    if fallback and fallback[0] in files(rev) and func in classes(fallback[0], rev).get(fallback[1], ((), {}))[1]:
        return fallback
    return None


@cache
def renames(base):
    """{old path: new path} of files renamed in base..REV (per commit, chained)."""
    out = {}
    for line in reversed(git("log", "-M", "--diff-filter=R", "--name-status", "--format=", f"{base}..{REV}").splitlines()):
        if (p := line.split("\t"))[0].startswith("R"):
            out = {k: p[2] if v == p[1] else v for k, v in out.items()} | {p[1]: p[2]}
    return out


def gone(base, src, func):
    """(deleting commit, new places `file::Class::test`: file renamed, same name in another file, or test renamed)."""
    out = git("log", f"{base}..{REV}", LOG_FMT, "--name-only", f"-Sdef {func}(", "--", "*.py")
    sha, moved = None, set()
    if new := renames(base).get(src):
        moved |= {f"{new}::{cls}::{func}" for cls, (_, fs) in classes(new, REV).items() if func in fs}
    for c in out.split("COMMIT\x1f")[1:]:
        head, *paths = c.strip().splitlines()
        sha = sha or (head.split("\x1f")[0] if src in paths else None)
        moved |= {f"{p}::{cls}::{func}" for p in paths if p != src and p in files(REV)
                  for cls, (_, fs) in classes(p, REV).items() if func in fs}
    sha = sha or git("log", "-1", "--format=%H", f"{base}..{REV}", "--", src).strip()
    if not moved and src in files(REV):
        added = re.findall(r"^\+\s*(?:async\s+)?def (test_\w+)\(", git("show", "--format=", sha, "--", src), re.M)
        now = {n: cls for cls, (_, fs) in classes(src, REV).items() for n in fs}
        moved = {f"{src}::{now[n]}::{n}" for n in difflib.get_close_matches(func, [n for n in added if n in now], 1, 0.8)}
    return sha, sorted(moved)


def issue_refs(text):
    for full, n1, repo, short, n2 in ISSUE.findall(text):
        yield f"{full}#{n1}" if full else f"{repo or REPOS.get(short, f'scylladb/{short}')}#{n2}"


def closed_issues(analyses):
    """{issue ref: True if closed} for refs in `open-issue` notes."""
    refs_ = sorted({r for a in analyses.values() for t in a["tests"].values() for i in t["issues"]
             if i["tag"] == "open-issue" for r in issue_refs(f"{i['ref']} {i['text']}")})

    def state(ref):
        repo, n = ref.split("#")
        r = subprocess.run(["gh", "api", f"repos/{repo}/issues/{n}", "--jq", ".state"], capture_output=True, text=True)
        if r.returncode:
            print(f"warning: {ref}: {r.stderr.strip()}", file=sys.stderr)
        return r.stdout.strip() == "closed"
    with ThreadPoolExecutor(8) as ex:
        return dict(zip(refs_, ex.map(state, refs_)))


@cache
def ports(base):
    """[(sha, message, added path::test)] for scylla commits in base..SCYLLA_REV that mention or touch dtest."""
    shas = scylla("log", "--format=%H", "-i", "--grep=dtest", f"{base}..{SCYLLA_REV}", "--", "test/").split()
    shas += scylla("log", "--format=%H", f"{base}..{SCYLLA_REV}", "--", "test/cluster/dtest/").split()
    out = []
    for sha in dict.fromkeys(shas):
        msg, path, added = scylla("log", "-1", "--format=%B", sha), None, []
        for line in scylla("show", "--format=", "-U0", sha, "--", "test/").splitlines():
            if line.startswith("+++ "):
                path = line[6:]
            elif m := re.match(r"\+\s*(?:async\s+)?def (test_\w+)", line):
                added.append(f"{path}::{m[1]}")
        out.append((sha, msg, added))
    return out


def triggers(mod, a, closed):
    """Yield (key, KIND, detail) for one module."""
    path, base = a["file"], a["dtest_rev"]
    changed_files, changed_defs = changed(base)
    stem = path.removesuffix(".py").rsplit("/", 1)[-1]
    named = {}  # sha -> words of commits naming the module, camelCase also as snake_case
    for sha, msg, _ in ports(a["scylla_rev"]):
        if re.search(rf"\b{re.escape(stem)}\b", msg):
            words = set(re.findall(r"\b\w+\b(?!\.py)", msg))
            named[sha] = words | {re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", w).lower() for w in words}
            if not any(k.split("::")[1] in named[sha] for k in a["tests"]):
                yield "*", "PORTED", f"{sha[:10]} (names {stem}, no test)"
    for key, t in a["tests"].items():
        if t["decision"] == "DELETED":
            continue
        cls, func = key.split("::")
        was = find(path, cls, func, base)
        now = find(path, cls, func, REV, fallback=was)
        if now is None:
            sha, moved = gone(base, (was or (path,))[0], func)
            yield (key, "MOVED", ",".join(moved)) if moved else (key, "DELETED", sha)
            continue
        src, owner = now
        if src in changed_files or path in changed_files:
            if was is None or ast.dump(defs(was[0], base)[f"{was[1]}.{func}"]) != ast.dump(defs(src, REV)[f"{owner}.{func}"]):
                start, end = classes(src, REV)[owner][1][func]
                log = git("log", f"{base}..{REV}", LOG_FMT, "--no-patch", "-L", f"{start},{end}:{src}")
                yield key, "CHANGED", ",".join(c["sha"][:10] for c in parse_log(log)) or "not at dtest_rev"
        if {f for f, _ in changed_defs} & scope(path, src) and (hit := changed_defs & reach(path, cls, src, owner, func) - {(src, f"{owner}.{func}")}):
            yield key, "HELPER", ",".join(sorted(f"{f}:{q}" for f, q in hit))
        if done := [r for i in t["issues"] if i["tag"] == "open-issue"
                    for r in issue_refs(f"{i['ref']} {i['text']}") if closed.get(r)]:
            yield key, "ISSUE", ",".join(dict.fromkeys(done))
        hits = [f"{sha[:10]} {p}" for sha, _, added in ports(a["scylla_rev"]) for p in added if p.endswith(f"::{func}")]
        hits += [f"{sha[:10]} (names {func})" for sha, words in named.items() if func in words]
        if hits:
            yield key, "PORTED", ",".join(dict.fromkeys(hits))


def main():
    args = sys.argv[1:]
    if args[:1] == ["--bump"]:
        dtest, scylla_rev, *mods = args[1:]
        for mod in mods:
            a = load(mod)
            a |= {"scylla_rev": scylla_rev, "dtest_rev": dtest}
            save(mod, a)
        return
    apply = "--apply" in args
    mods = [m for m in args if m != "--apply"] or sorted(p.stem for p in (ROOT / "analysis").glob("*.json"))
    dtest_rev, scylla_rev = git("rev-parse", REV).strip(), scylla("rev-parse", "--short", SCYLLA_REV).strip()
    print(f"# dtest_rev {dtest_rev} scylla_rev {scylla_rev}")
    analyses = {mod: load(mod) for mod in mods}
    closed = closed_issues(analyses)
    prs = PRs()
    for mod, a in analyses.items():
        found = list(triggers(mod, a, closed))
        for key, kind, detail in found:
            print(mod, key, kind, detail)
        if not apply:
            continue
        deleted = [(key, sha) for key, kind, sha in found if kind == "DELETED"]
        for key, sha in deleted:
            t = a["tests"][key]
            pr = prs.get(sha)
            t["deleted"] = {"sha": sha, "date": git("log", "-1", "--format=%as", sha).strip(),
                            "pr": pr and pr["number"], "prev": t["decision"]}
            t["decision"] = "DELETED"
        if len(deleted) == len(found):
            a |= {"scylla_rev": scylla_rev, "dtest_rev": dtest_rev}
        save(mod, a)
    prs.save()


if __name__ == "__main__":
    main()
