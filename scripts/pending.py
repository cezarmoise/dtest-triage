#!/usr/bin/env python3
"""List analysis work left: one line per chunk, `<module> <Class::test,...>` (max N tests per chunk).

usage: pending.py [N]   (default 10)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
for mod in json.loads((ROOT / "data/index.json").read_text()):
    tests = [f"{t['class']}::{t['name']}" for t in json.loads((ROOT / f"data/{mod}.json").read_text())["tests"]]
    a = ROOT / f"analysis/{mod}.json"
    done = set(json.loads(a.read_text())["tests"]) if a.exists() else set()
    todo = [t for t in tests if t not in done]
    for i in range(0, len(todo), n):
        print(mod, ",".join(todo[i:i + n]))
