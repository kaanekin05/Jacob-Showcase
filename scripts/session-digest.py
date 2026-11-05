#!/usr/bin/env python3
"""Shrink Claude Code session transcripts to the turns that matter for /session-finalizer.

Usage:
  session-digest.py                 # current session ($CLAUDE_CODE_SESSION_ID)
  session-digest.py <id> [<id> ...] # specific sessions (full id or unique prefix)
  session-digest.py today           # every session in this project modified today
  session-digest.py --list          # list this project's sessions, newest first

Keeps: user messages, assistant text, AskUserQuestion calls and answers,
files written or edited, git commit/push commands. Drops tool output,
thinking, hook noise, and subagent (sidechain) turns.
"""
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
TEXT_CAP = 4000  # per assistant message; the head and the tail are kept

NOISE_BLOCKS = re.compile(
    r"<(system-reminder|task-notification|local-command-stdout|local-command-caveat)>.*?</\1>",
    re.S,
)
COMMAND_NAME = re.compile(r"<command-name>(.*?)</command-name>", re.S)
COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)
OTHER_TAGS = re.compile(r"</?command-(message|name|args)>")
NOTICE = re.compile(r"\[SYSTEM NOTIFICATION - NOT USER INPUT\].*?(?=\n\n|\Z)", re.S)
GIT_CMD = re.compile(r"\bgit\s+(commit|push|tag|stash|reset)\b")


def project_dir() -> Path:
    return PROJECTS / re.sub(r"[^A-Za-z0-9]", "-", os.getcwd())


def resolve(arg: str) -> Path:
    local = list(project_dir().glob(f"{arg}*.jsonl"))
    hits = local or list(PROJECTS.glob(f"*/{arg}*.jsonl"))
    if len(hits) != 1:
        sys.exit(f"session '{arg}': {len(hits)} matches, need exactly 1")
    return hits[0]


def cap(text: str) -> str:
    if len(text) <= TEXT_CAP:
        return text
    half = TEXT_CAP // 2
    return f"{text[:half]}\n[... {len(text) - TEXT_CAP} chars cut ...]\n{text[-half:]}"


def clean_user(text: str) -> str:
    name = COMMAND_NAME.search(text)
    args = COMMAND_ARGS.search(text)
    if name:
        return f"{name.group(1).strip()} {args.group(1).strip() if args else ''}".strip()
    text = NOISE_BLOCKS.sub("", text)
    text = NOTICE.sub("", text)
    return OTHER_TAGS.sub("", text).strip()


def digest(path: Path) -> str:
    lines, title, first, last = [], "", None, None
    ask_ids = set()
    for raw in path.open(encoding="utf-8"):
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        kind = rec.get("type")
        if kind == "ai-title":
            title = rec.get("aiTitle") or rec.get("title") or title
        if kind not in ("user", "assistant") or rec.get("isSidechain") or rec.get("isMeta"):
            continue
        stamp = rec.get("timestamp", "")
        first = first or stamp
        last = stamp or last
        hhmm = stamp[11:16]
        content = (rec.get("message") or {}).get("content")
        if rec.get("isCompactSummary"):
            lines.append(f"[{hhmm} COMPACTED] {cap(str(content))}")
            continue
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for part in content or []:
            ptype = part.get("type")
            if kind == "user" and ptype == "text":
                text = clean_user(part.get("text", ""))
                if text:
                    lines.append(f"[{hhmm} USER] {text}")
            elif kind == "user" and ptype == "tool_result" and part.get("tool_use_id") in ask_ids:
                body = part.get("content")
                if isinstance(body, list):
                    body = " ".join(b.get("text", "") for b in body if isinstance(b, dict))
                lines.append(f"[{hhmm} ANSWER] {str(body).strip()}")
            elif kind == "assistant" and ptype == "text" and part.get("text", "").strip():
                lines.append(f"[{hhmm} CLAUDE] {cap(part['text'].strip())}")
            elif kind == "assistant" and ptype == "tool_use":
                name, inp = part.get("name"), part.get("input") or {}
                if name == "AskUserQuestion":
                    ask_ids.add(part.get("id"))
                    for q in inp.get("questions", []):
                        opts = " | ".join(o.get("label", "") for o in q.get("options", []))
                        lines.append(f"[{hhmm} ASKED] {q.get('question', '')}  Options: {opts}")
                elif name in ("Write", "Edit", "NotebookEdit"):
                    lines.append(f"[{hhmm} WROTE] {inp.get('file_path') or inp.get('notebook_path')}")
                elif name == "Bash" and GIT_CMD.search(inp.get("command", "")):
                    cmd = inp["command"].splitlines()[0][:200]
                    lines.append(f"[{hhmm} GIT] {cmd}")
    head = f"=== SESSION {path.stem} | {title or 'untitled'} | {first} -> {last} ==="
    return "\n".join([head, *lines, ""])


def sessions_today() -> list:
    today = dt.date.today()
    files = [p for p in project_dir().glob("*.jsonl")
             if dt.date.fromtimestamp(p.stat().st_mtime) == today]
    return sorted(files, key=lambda p: p.stat().st_mtime)


def main(argv: list) -> None:
    if argv == ["--list"]:
        for p in sorted(project_dir().glob("*.jsonl"), key=lambda p: -p.stat().st_mtime)[:20]:
            when = dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            print(f"{when}  {p.stem}  {p.stat().st_size // 1024} KB")
        return
    if argv == ["today"]:
        paths = sessions_today()
    elif argv:
        paths = [resolve(a) for a in argv]
    else:
        sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
        if not sid:
            sys.exit("no session given and CLAUDE_CODE_SESSION_ID is not set")
        paths = [resolve(sid)]
    if not paths:
        sys.exit("no sessions found")
    for p in paths:
        print(digest(p))


if __name__ == "__main__":
    main(sys.argv[1:])
