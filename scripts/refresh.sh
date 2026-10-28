#!/bin/bash
# Merge new Jenkins builds into jenkins/*_long.csv, fetch dtest/scylla, regenerate data/
set -euo pipefail
cd "$(dirname "$0")/.."
for j in dtest-release dtest-release-with-raft; do
  python3 scripts/test_results.py --job scylla-master/$j -o jenkins/$j
done
python3 scripts/test_results.py --job scylla-master/next --stage 'dtest with tablets' -o jenkins/next-dtest-tablets
python3 scripts/test_results.py --job scylla-master/next \
  --stage 'dtest with consistent topology changes' -o jenkins/next-dtest-consistent-topology
git -C ~/github/scylla-dtest fetch -q upstream next
git -C ~/github/scylladb fetch -q upstream master
python3 scripts/gen_data.py
