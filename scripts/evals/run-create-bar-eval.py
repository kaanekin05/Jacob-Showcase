"""Create-bar eval: does the judge allow the skills Kaan keeps and deny the ones he called too small?

Each case is a real learned skill, rebuilt as the `stage_skill` create intent the reflector
would send, or a synthetic one-liner. The judge is the same prompt and model call the hook
uses (scripts/hooks/create_bar.py). The labels are Kaan's own, from 2026-11-06.

A miss means the rubric is wrong, never the label. Change scripts/hooks/create-bar-rubric.md
and rerun. Label disagreements are Kaan's to settle.

Usage:
  python3 -I scripts/evals/run-create-bar-eval.py              # all cases, 1 trial each
  python3 -I scripts/evals/run-create-bar-eval.py git          # cases whose name contains "git"
  TRIALS=3 python3 -I scripts/evals/run-create-bar-eval.py     # majority of 3 per case
  CREATE_BAR_MODEL=claude-sonnet-5-5 python3 -I scripts/evals/run-create-bar-eval.py

Cost: one model call per case per trial. Read-only.
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

JACOB_ROOT = Path(os.environ.get("JACOB_ROOT") or "/Users/kaan/Workspace/Jacob")
sys.path.insert(0, str(JACOB_ROOT / "scripts" / "hooks"))
import create_bar  # noqa: E402

CASES = JACOB_ROOT / "scripts" / "evals" / "create-bar-cases.jsonl"
SKILLS = JACOB_ROOT / "skills"
SUBDIRS = ("references", "scripts", "templates", "assets")


def intent_from_skill(name: str) -> dict:
    folder = SKILLS / name
    files = {}
    for sub in SUBDIRS:
        for path in sorted((folder / sub).rglob("*")):
            if path.is_file() and not path.name.startswith("evidence-"):
                files[str(path.relative_to(folder))] = path.read_text(encoding="utf-8", errors="replace")
    return {"action": "create", "name": name, "level": "global",
            "body": (folder / "SKILL.md").read_text(encoding="utf-8"),
            "reason": "lesson distilled from a session", "files": files}


def judge_once(tool_input: dict, model: str, ruleset: str, rubric: str) -> str:
    index = sorted(create_bar.skill_index([SKILLS], exclude=tool_input["name"])
                   + create_bar.command_index(JACOB_ROOT / "commands"))
    prompt = create_bar.build_prompt(tool_input, index, ruleset, rubric)
    try:
        verdict = create_bar.parse_verdict(create_bar.call_claude(prompt, model))
    except Exception as exc:  # an error is a miss, never a pass
        return f"error: {type(exc).__name__}"
    return "allow" if verdict["allow"] else "deny"


def main() -> int:
    flt = sys.argv[1] if len(sys.argv) > 1 else ""
    trials = int(os.environ.get("TRIALS", "1"))
    model = os.environ.get("CREATE_BAR_MODEL") or create_bar.DEFAULT_MODEL
    ruleset = (JACOB_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    rubric = create_bar.RUBRIC_PATH.read_text(encoding="utf-8")
    cases = [json.loads(line) for line in CASES.read_text().splitlines() if line.strip()]
    jobs = []
    for case in cases:
        intent = case["synthetic"] | {"action": "create", "reason": "lesson distilled from a session"} \
            if "synthetic" in case else intent_from_skill(case["skill"])
        if flt in intent["name"]:
            jobs.append((case, intent))

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [[pool.submit(judge_once, intent, model, ruleset, rubric) for _ in range(trials)]
                   for _, intent in jobs]
        results = [[f.result() for f in fs] for fs in futures]

    print(f"# Create-bar eval · model: {model} · trials: {trials}\n")
    print("| case | expected | got | ok |\n|---|---|---|---|")
    passed = 0
    for (case, intent), got in zip(jobs, results):
        majority = max(set(got), key=got.count)
        ok = majority == case["expect"] and got.count(majority) * 2 > len(got)
        passed += ok
        print(f"| {intent['name']} | {case['expect']} | {', '.join(got)} | {'✓' if ok else '✗'} |")
    print(f"\n**{passed}/{len(jobs)} passed**")
    return 0 if passed == len(jobs) else 1


if __name__ == "__main__":
    sys.exit(main())
