"""List epics.md stories whose hard dependencies are all `done` in sprint-status.yaml.

Run from the repo root:  uv run -q --with pyyaml python _bmad-output/implementation-artifacts/orchestration/ready.py
Feature epics (E1–E10) are printed with a [gated] tag: they wait for the Phase 0 exit gate.
"""
import re
import yaml

EPICS = "_bmad-output/planning-artifacts/epics.md"
SS = "_bmad-output/implementation-artifacts/sprint-status.yaml"

ep = open(EPICS).read()
txt = open(SS).read()
ss = yaml.safe_load(txt)["development_status"]
emap = {m[1]: m[0] for m in re.findall(r"#   epic-(\d+) = (\S+)", txt)}


def key(sid: str):
    e, n = sid.rsplit(".", 1)
    return next((k for k in ss if k.startswith(f"{emap[e]}-{n}-")), None)


stories = re.split(r"\n### Story ", ep)[1:]
done = {s.split(":")[0].strip() for s in stories if ss.get(key(s.split(":")[0].strip())) == "done"}
for s in stories:
    sid = s.split(":")[0].strip()
    title = s.split("\n")[0].split(":", 1)[1].strip()
    if sid in done or "OPTIONAL" in s[:400]:
        continue
    dm = re.search(r"\*\*Dependencies:\*\*(.*?)(\*\*Size|\n\n)", s, re.S)
    hard = (dm.group(1) if dm else "").split("Soft:")[0]
    ids = set(re.findall(r"\bE(?:0a|0-[A-Za-z]+|\d+)\.\d+\b", hard))
    if ids <= done:
        gated = "" if sid.startswith("E0") else " [gated]"
        print(f"{sid:16s}{gated}  {title[:80]}")
