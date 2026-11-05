#!/usr/bin/env python3
"""Emit the routing roster the trigger eval scores against: every name + description
a prompt could plausibly route to.

Why this is its own file: the descriptions live in YAML frontmatter, and Jacob's use
every scalar style there is — plain, quoted, and `>-` folded blocks that run to nine
lines. An awk one-liner silently returns ">-" for the folded ones, which puts a skill
in the roster with an empty description and makes it look like it under-fires. Parse
the frontmatter properly or don't parse it at all.

Three sources, because a prompt can route to any of them:
  skills/*/SKILL.md   — keyed by DIRECTORY name, which is what the harness presents
                        and what the user types. Five skills declare a frontmatter
                        `name:` that differs from their directory (unity-mcp-skill
                        declares unity-mcp-orchestrator, code-review-standards
                        declares code-review, ...); the directory wins, and the
                        frontmatter name is carried as an alias so a near-miss answer
                        is still scored as the right skill. doctor Check 12 warns on
                        the divergence so it stays visible.
  agents/*.md         — keyed by filename stem; dispatch targets that cases expect too
  PLUGIN_SKILLS       — installed via plugin, nothing on disk here to read

Usage: build-roster.py [--json]
"""
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

# Plugin-provided skills have no SKILL.md inside Jacob, so their descriptions are
# mirrored here by hand. Keep only the ones trigger-cases.jsonl actually references —
# an incomplete mirror is fine, a stale one is not. Re-copy from the plugin's own
# frontmatter when a case starts depending on a new one.
PLUGIN_SKILLS = {
    "memsearch:memory-to-skill": (
        "Turn workflows from your MemSearch memory into reusable skills. Use when the "
        "user asks to make/create/extract/distill a skill from what they just did or "
        "from past work, review skill candidates, install a distilled skill, or 'turn "
        "this into a skill'. Manages MemSearch procedural-memory candidates under "
        ".memsearch/skill-candidates/, not Claude Code's own skills system."
    ),
    "memsearch:memory-recall": (
        "Search and recall relevant memories from past sessions via memsearch. Use when "
        "the user's question could benefit from historical context, past decisions, "
        "debugging notes, previous conversations, or project knowledge -- especially "
        "questions like 'what did I decide about X' or 'why did we do Y'."
    ),
    "superpowers:brainstorming": (
        "You MUST use this before any creative work - creating features, building "
        "components, adding functionality, or modifying behavior. Explores user intent, "
        "requirements and design before implementation."
    ),
    "anthropic-skills:skill-creator": (
        "Create new skills, modify and improve existing skills, and measure skill "
        "performance. Use when users want to create a skill from scratch, edit, or "
        "optimize an existing skill, run evals to test a skill, benchmark skill "
        "performance with variance analysis, or optimize a skill's description for "
        "better triggering accuracy."
    ),
    "plugin-dev:skill-development": (
        "This skill should be used when the user wants to \"create a skill\", \"add a "
        "skill to plugin\", \"write a new skill\", \"improve skill description\", "
        "\"organize skill content\", or needs guidance on skill structure, progressive "
        "disclosure, or skill development best practices for Claude Code plugins."
    ),
    "plugin-dev:agent-development": (
        "This skill should be used when the user asks to \"create an agent\", \"add an "
        "agent\", \"write a subagent\", \"agent frontmatter\", \"when to use "
        "description\", \"agent examples\", \"agent tools\", \"agent colors\", "
        "\"autonomous agent\", or needs guidance on agent structure, system prompts, "
        "triggering conditions, or agent development best practices for Claude Code plugins."
    ),
    # A plugin AGENT, not a skill, mirrored here for the same reason.
    "plugin-dev:skill-reviewer": (
        "Use this agent when the user has created or modified a skill and needs quality "
        "review, asks to \"review my skill\", \"check skill quality\", \"improve skill "
        "description\", or wants to ensure skill follows best practices. Trigger "
        "proactively after skill creation."
    ),
    "superpowers:systematic-debugging": (
        "Use when encountering any bug, test failure, or unexpected behavior, before "
        "proposing fixes."
    ),
}


def frontmatter(path: Path) -> dict:
    """Return the YAML frontmatter block, or {} if the file has none/invalid."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        data = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def collect() -> list[dict]:
    out, seen = [], set()

    def add(name, desc, kind, src, alias=None):
        name = (name or "").strip()
        desc = " ".join((desc or "").split())
        if not name or name in seen:
            return
        seen.add(name)
        entry = {"name": name, "description": desc, "kind": kind, "source": src}
        if alias and alias.strip() and alias.strip() != name:
            entry["alias"] = alias.strip()
        out.append(entry)

    for skill_md in sorted((ROOT / "skills").glob("*/SKILL.md")):
        fm = frontmatter(skill_md)
        # The DIRECTORY is the routing key — it is what the harness lists and what the
        # user types. The frontmatter name: rides along as an alias for scoring only.
        add(skill_md.parent.name, fm.get("description"), "skill",
            str(skill_md.relative_to(ROOT)), alias=fm.get("name"))

    for agent_md in sorted((ROOT / "agents").glob("*.md")):
        if agent_md.name == "AGENTS.md":
            continue
        fm = frontmatter(agent_md)
        add(agent_md.stem, fm.get("description"), "agent",
            str(agent_md.relative_to(ROOT)), alias=fm.get("name"))

    for name, desc in PLUGIN_SKILLS.items():
        add(name, desc, "plugin-skill", "mirrored in build-roster.py")

    return out


def main() -> int:
    roster = collect()
    missing = [r["name"] for r in roster if not r["description"]]

    if "--json" in sys.argv:
        print(json.dumps(roster, indent=2))
    else:
        for r in roster:
            # Mark agents so the router knows dispatching one is a valid answer;
            # unmarked entries are skills. Consumers match on the leading "- <name>".
            kind = " (agent)" if r["kind"] == "agent" else ""
            print(f"- {r['name']}{kind}: {r['description']}")

    if missing:
        print(
            f"\n# WARNING: {len(missing)} entr(ies) have an empty description and "
            f"cannot route: {', '.join(missing)}",
            file=sys.stderr,
        )
    print(
        f"# roster: {len(roster)} entries "
        f"({sum(r['kind'] == 'skill' for r in roster)} skills, "
        f"{sum(r['kind'] == 'agent' for r in roster)} agents, "
        f"{sum(r['kind'] == 'plugin-skill' for r in roster)} plugin skills)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
