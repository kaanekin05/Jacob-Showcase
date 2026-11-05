"""PreToolUse hook: judge autoharness `create` intents against Kaan's create bar.

Spec: docs/superpowers/specs/2026-11-06-autoharness-create-bar-design.md

Autoharness's reflector is told to create a skill whenever it is unsure. This hook
stops new skills that carry no more than a sentence the user could just say. It judges
only `create` calls from an autoharness child session, and lets everything else through:
patches, merges, deletes, curator umbrellas, and the user's own /learn.

Allow is silent. Deny prints one PreToolUse JSON object. Every failure allows, because a
missed deny costs one small skill that cleanup can merge, while a wrong deny loses a
lesson for good.
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import AbstractSet, Callable, Mapping, Optional, TextIO

DEFAULT_JACOB_ROOT = "/Users/kaan/Workspace/Jacob"
DEFAULT_MODEL = "claude-sonnet-5-5"  # Haiku denied 7 of 9 keepers in the eval
CHILD_ENV = "AUTOHARNESS_CHILD_SESSION"
FILES_BUDGET = 6000
RUBRIC_PATH = Path(__file__).resolve().parent / "create-bar-rubric.md"


def should_judge(event: dict, env: Mapping[str, str]) -> bool:
    if not str(event.get("tool_name") or "").endswith("__stage_skill"):
        return False
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict) or tool_input.get("action") != "create":
        return False
    if not env.get(CHILD_ENV):
        return False  # the user's own /learn runs in their session, not a child
    return not str(event.get("agent_type") or "").endswith(":curator")


def parse_verdict(text: str) -> dict:
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            obj, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict) and obj.get("verdict") in ("allow", "deny"):
            return {"allow": obj["verdict"] == "allow",
                    "closest": str(obj.get("closest") or ""),
                    "why": str(obj.get("why") or "")}
        start = text.find("{", start + 1)
    raise ValueError("no valid verdict in judge reply")


def deny_reason(verdict: dict, patchable: AbstractSet[str]) -> str:
    # autoharness rejects a patch to any skill it did not create (validate.py self_produced),
    # so only a skill in `patchable` may be offered as a patch target.
    why = verdict.get("why", "").strip() or "it is a rule that fits in one sentence."
    if not why.endswith((".", "!", "?")):
        why += "."
    closest = verdict.get("closest", "").strip()
    if not closest:
        tail = "Add it as a line to the closest skill autoharness created, or skip it."
    elif closest in patchable:
        tail = f"Patch it into `{closest}` as a line, or skip it."
    else:
        tail = f"`{closest}` already covers it, and autoharness cannot patch that skill, so skip it."
    return f"Below the create bar: {why} {tail}"


def _clean(value: str) -> str:
    return " ".join(str(value).split())


def log_verdict(path: Path, name: str, level: str, outcome: str, reason: str) -> None:
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    line = "\t".join([stamp, _clean(name), _clean(level), outcome, _clean(reason)]) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass  # logging never changes the decision


def decide(event: dict, env: Mapping[str, str], judge: Callable[[str], str],
           build: Callable[[dict], str], log_path: Path,
           patchable: AbstractSet[str] = frozenset()) -> Optional[dict]:
    if not should_judge(event, env):
        return None
    tool_input = event["tool_input"]
    name, level = str(tool_input.get("name") or ""), str(tool_input.get("level") or "")
    try:
        verdict = parse_verdict(judge(build(tool_input)))
    except Exception as exc:  # fail open: any judge failure allows
        log_verdict(log_path, name, level, "error", f"{type(exc).__name__}: {exc}"[:300])
        return None
    if verdict["allow"]:
        log_verdict(log_path, name, level, "allow", verdict["why"])
        return None
    reason = deny_reason(verdict, patchable)
    log_verdict(log_path, name, level, "deny", reason)
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def _frontmatter(text: str) -> dict:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields, key = {}, None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line[:1] in (" ", "\t") and key:  # continuation of a folded value
            fields[key] = (fields[key] + " " + line.strip()).strip()
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            key, value = key.strip(), value.strip()
            fields[key] = "" if value in (">", "|", ">-", "|-") else value.strip("'\"")
    return fields


def skill_index(roots: list, exclude: Optional[str] = None) -> list:
    entries = {}
    for root in roots:
        for skill_md in sorted(Path(root).glob("*/SKILL.md")):
            try:
                fields = _frontmatter(skill_md.read_text(encoding="utf-8"))
            except OSError:
                continue
            name = fields.get("name") or skill_md.parent.name
            if name != exclude:
                entries.setdefault(name, fields.get("description", ""))
    return sorted(entries.items())


def agent_skills(roots: list) -> set:
    found = set()
    for root in roots:
        for sidecar in Path(root).glob("*/.sidecar.json"):
            try:
                if json.loads(sidecar.read_text(encoding="utf-8")).get("created_by") == "agent":
                    found.add(sidecar.parent.name)
            except (OSError, ValueError, AttributeError):
                continue
    return found


def command_index(root: Path) -> list:
    # Commands are invocable like skills, so a skill that repeats one is a duplicate too.
    entries = []
    for md in sorted(Path(root).glob("*.md")):
        try:
            entries.append((md.stem, _frontmatter(md.read_text(encoding="utf-8")).get("description", "")))
        except OSError:
            continue
    return entries


def _files_section(files: dict, budget: int) -> str:
    parts, left, cut = [], budget, False
    for path in sorted(files):
        content = str(files[path])
        if len(content) > left:
            content, cut = content[:left], True
        left -= len(content)
        parts.append(f"--- {path} ---\n{content}")
    if cut:
        parts.append("[truncated]")
    return "\n".join(parts)


def build_prompt(tool_input: dict, index: list, ruleset: str, rubric: str,
                 files_budget: int = FILES_BUDGET) -> str:
    # `evidence` quotes the user's session, so it never goes to the judge.
    index_lines = "\n".join(f"{name}: {desc}" for name, desc in index)
    files = tool_input.get("files") or {}
    return "\n\n".join([
        rubric,
        f"<ruleset>\n{ruleset}\n</ruleset>",
        f"<skill_index>\n{index_lines}\n</skill_index>",
        "<proposed_skill>\n"
        f"name: {tool_input.get('name', '')}\n"
        f"level: {tool_input.get('level', '')}\n"
        f"reason: {tool_input.get('reason', '')}\n"
        f"<body>\n{tool_input.get('body', '')}\n</body>\n"
        f"<files>\n{_files_section(files, files_budget) if files else '(none)'}\n</files>\n"
        "</proposed_skill>",
        "Reply with the JSON object only.",
    ])


def call_claude(prompt: str, model: str, timeout: float = 60) -> str:
    binary = os.environ.get("CLAUDE_BIN") or shutil.which("claude")
    if not binary:
        raise RuntimeError("claude CLI not found on PATH")
    # --safe-mode drops CLAUDE.md, plugins and hooks, so the judge sees only the prompt the
    # eval measured, and no plugin hook (memsearch, Orca, superpowers) runs for it.
    argv = [binary, "-p", "--safe-mode", "--model", model, "--tools", "", "--strict-mcp-config",
            "--no-session-persistence", "--output-format", "text"]
    # The child-session flag keeps autoharness from capturing and reflecting on the judge.
    env = {**os.environ, CHILD_ENV: "1"}
    proc = subprocess.run(argv, input=prompt, capture_output=True, text=True, env=env, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr.strip()[:200]}")
    return proc.stdout


def skill_roots(env: Mapping[str, str]) -> list:
    roots = [Path.home() / ".claude" / "skills"]
    if env.get("CLAUDE_PROJECT_DIR"):
        roots.append(Path(env["CLAUDE_PROJECT_DIR"]) / ".claude" / "skills")
    return roots


def default_build(tool_input: dict, env: Mapping[str, str] = os.environ) -> str:
    roots = skill_roots(env)
    jacob_root = Path(env.get("JACOB_ROOT") or DEFAULT_JACOB_ROOT)
    index = sorted(skill_index(roots, exclude=str(tool_input.get("name") or ""))
                   + command_index(Path.home() / ".claude" / "commands"))
    ruleset = (jacob_root / "AGENTS.md").read_text(encoding="utf-8")
    return build_prompt(tool_input, index, ruleset, RUBRIC_PATH.read_text(encoding="utf-8"))


def main(stdin: TextIO, stdout: TextIO, env: Mapping[str, str]) -> int:
    try:
        event = json.loads(stdin.read())
        if not isinstance(event, dict):
            return 0
        log_path = Path(env.get("JACOB_ROOT") or DEFAULT_JACOB_ROOT) / ".state" / "create-bar.log"
        model = env.get("CREATE_BAR_MODEL") or DEFAULT_MODEL
        out = decide(event, env, lambda prompt: call_claude(prompt, model),
                     lambda tool_input: default_build(tool_input, env), log_path,
                     patchable=agent_skills(skill_roots(env)))
        if out is not None:
            stdout.write(json.dumps(out) + "\n")
    except Exception:
        pass  # fail open, and never print a traceback to stdout
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.stdin, sys.stdout, os.environ))
