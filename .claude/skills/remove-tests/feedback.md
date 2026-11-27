# Apply a PR agent's triage report (run in ~/github/dtest-triage)

Input: `/home/cezar/.cache/claude/dtest-triage-inbox/<branch>.json`, written by a removal PR agent (pr.md step 6,
review.md step 6). It arrives as a prompt "Triage report from <branch> …", or `/weekly` finds it in the inbox.
Format: `scripts/removal.py` docstring (`feedback`). The agent checked each item; check its evidence again before
writing (the agent can be wrong too). Wrong item → skip it, say why in the reply.

1. `git pull --rebase -q`; `python3 scripts/removal.py feedback <file>` prints `OK` (else tell the agent:
   `herdr agent prompt rm-<branch> "<errors>"`, or the user if it's gone). A copy in `…/inbox/done/` for the
   same branch → apply only the items it lacks (reports are rewritten whole).
2. Per item, edit the test's entry in `analysis/<module>.json` (`<Class>::<test>`), rubric and tags as in
   `.claude/skills/analyze/prompt.md` steps 5-7:
   - `kept`: the test stays in dtest. Its duplicate → `partial` (note = the gap) or dropped; decision per the
     rubric (usually YELLOW); `reason` starts `Kept in scylla-dtest#<pr>: <why>.` `jira` stays.
   - `dup`: replace/add that duplicate (`none` → drop it). No `full` duplicate left → decision per the rubric.
   - `claim`: fix the statement in `reason`/`issues`/`description`.
   - `issue`: add it to `issues`, and its `Bug:`/`Note:` mention to `reason`.
   - `followup`: nothing to edit; goes in the reply.
   An entry with `review` (dev verdict): its decision is final, fix only the text.
3. `python3 scripts/check_analysis.py <modules>`; `git commit -m "analysis: report <branch>" analysis/`; push (CLAUDE.md
   commit rule). Then `mkdir -p …/inbox/done && mv <file> …/inbox/done/<branch>.json`.
4. Reply: per item what changed (decision changes first: RED → YELLOW keeps the Jira issue open), skipped items
   and why, `followup` items for the user.
