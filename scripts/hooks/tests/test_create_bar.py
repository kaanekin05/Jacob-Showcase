import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import create_bar

TOOL = "mcp__plugin_autoharness_stage_skill__stage_skill"
CHILD = {"AUTOHARNESS_CHILD_SESSION": "1"}


def event(action="create", agent_type="autoharness:reflector", tool=TOOL, body="Do the thing."):
    ev = {"tool_name": tool, "tool_input": {"action": action, "name": "demo-skill", "level": "global",
                                            "body": body, "reason": "seen in session"}}
    if agent_type is not None:
        ev["agent_type"] = agent_type
    return ev


def judge_says(verdict, closest="", why="One sentence rule."):
    return lambda prompt: json.dumps({"verdict": verdict, "closest": closest, "why": why})


def build(tool_input):
    return "PROMPT for " + tool_input["name"]


class ShouldJudge(unittest.TestCase):
    def test_should_judge_only_child_creates(self):
        cases = [
            (event(), CHILD, True),
            (event(agent_type=None), CHILD, True),
            (event(action="patch"), CHILD, False),
            (event(action="update"), CHILD, False),
            (event(action="delete"), CHILD, False),
            (event(action="remove_file"), CHILD, False),
            (event(), {}, False),
            (event(agent_type="autoharness:curator"), CHILD, False),
            (event(tool="Write"), CHILD, False),
        ]
        for ev, env, expected in cases:
            with self.subTest(ev=ev, env=env):
                self.assertEqual(create_bar.should_judge(ev, env), expected)


class ParseVerdict(unittest.TestCase):
    EXPECTED = {"allow": False, "closest": "git-workflow", "why": "One rule."}
    RAW = '{"verdict":"deny","closest":"git-workflow","why":"One rule."}'

    def test_parse_verdict_plain(self):
        self.assertEqual(create_bar.parse_verdict(self.RAW), self.EXPECTED)

    def test_parse_verdict_fenced_and_prose(self):
        text = "Here is my verdict.\n```json\n" + self.RAW + "\n```\n"
        self.assertEqual(create_bar.parse_verdict(text), self.EXPECTED)

    def test_parse_verdict_rejects_garbage(self):
        for text in ("I think it's fine", '{"verdict":"maybe"}'):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    create_bar.parse_verdict(text)


class DenyReason(unittest.TestCase):
    def test_deny_reason_with_and_without_closest(self):
        with_closest = create_bar.deny_reason({"allow": False, "closest": "git-workflow", "why": "One rule."},
                                              {"git-workflow"})
        self.assertTrue(with_closest.startswith("Below the create bar:"))
        self.assertTrue(with_closest.endswith("Patch it into `git-workflow` as a line, or skip it."))
        without = create_bar.deny_reason({"allow": False, "closest": "", "why": "One rule."}, {"git-workflow"})
        self.assertTrue(without.startswith("Below the create bar:"))
        self.assertTrue(without.endswith("Add it as a line to the closest skill autoharness created, or skip it."))

    def test_deny_reason_unpatchable_closest_says_skip(self):
        # autoharness rejects a patch to any skill it did not create (validate.py self_produced)
        reason = create_bar.deny_reason({"allow": False, "closest": "sprite-gen", "why": "One rule."}, set())
        self.assertNotIn("Patch it into", reason)
        self.assertTrue(reason.endswith("`sprite-gen` already covers it, and autoharness cannot patch that skill, "
                                        "so skip it."))


class AgentSkills(unittest.TestCase):
    def test_agent_skills_reads_sidecar_created_by(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, sidecar in (("learned", '{"created_by": "agent"}'), ("native", None),
                                  ("human", '{"created_by": "human"}'), ("broken", "{not json")):
                d = Path(tmp) / name
                d.mkdir()
                if sidecar is not None:
                    (d / ".sidecar.json").write_text(sidecar)
            found = create_bar.agent_skills([Path(tmp), Path(tmp) / "missing-root"])
        self.assertEqual(found, {"learned"})


class Decide(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / ".state" / "create-bar.log"

    def tearDown(self):
        self.tmp.cleanup()

    def log_lines(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_decide_allow_is_none(self):
        self.assertIsNone(create_bar.decide(event(), CHILD, judge_says("allow"), build, self.log))
        lines = self.log_lines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].split("\t")[3], "allow")

    def test_decide_deny_shape(self):
        out = create_bar.decide(event(), CHILD, judge_says("deny", "git-workflow"), build, self.log,
                                patchable={"git-workflow"})
        self.assertEqual(out, {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": create_bar.deny_reason(
                {"allow": False, "closest": "git-workflow", "why": "One sentence rule."}, {"git-workflow"}),
        }})
        self.assertEqual(self.log_lines()[0].split("\t")[3], "deny")

    def test_decide_deny_unpatchable_logs_skip(self):
        out = create_bar.decide(event(), CHILD, judge_says("deny", "sprite-gen"), build, self.log)
        self.assertIn("cannot patch", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIn("cannot patch", self.log_lines()[0].split("\t")[4])

    def test_decide_skips_without_calling_judge(self):
        def judge(prompt):
            raise AssertionError("judge must not be called")
        self.assertIsNone(create_bar.decide(event(action="patch"), CHILD, judge, build, self.log))
        self.assertEqual(self.log_lines(), [])

    def test_decide_judge_timeout_allows(self):
        def judge(prompt):
            raise subprocess.TimeoutExpired(cmd="claude", timeout=60)
        self.assertIsNone(create_bar.decide(event(), CHILD, judge, build, self.log))
        self.assertEqual(self.log_lines()[0].split("\t")[3], "error")

    def test_decide_log_failure_keeps_decision(self):
        blocker = Path(self.tmp.name) / "a-file"
        blocker.write_text("x")
        bad_log = blocker / "sub" / "create-bar.log"
        out = create_bar.decide(event(), CHILD, judge_says("deny"), build, bad_log)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_log_never_holds_body(self):
        create_bar.decide(event(body="SECRET-BODY lives here"), CHILD, judge_says("deny"), build, self.log)
        self.assertNotIn("SECRET-BODY", self.log.read_text())


class Main(unittest.TestCase):
    def test_main_malformed_stdin_allows(self):
        for raw in ("", "not json", "{}"):
            with self.subTest(raw=raw):
                out = io.StringIO()
                with tempfile.TemporaryDirectory() as tmp:
                    rc = create_bar.main(io.StringIO(raw), out, {"JACOB_ROOT": tmp, **CHILD})
                self.assertEqual(rc, 0)
                self.assertEqual(out.getvalue(), "")


def write_skill(root, name, description):
    d = Path(root) / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n\nBody.\n")


class SkillIndex(unittest.TestCase):
    def test_skill_index_reads_frontmatter_and_excludes(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_skill(tmp, "zeta-skill", "Use when zeta.")
            write_skill(tmp, "alpha-skill", "Use when alpha.")
            write_skill(tmp, "demo-skill", "The skill being judged.")
            (Path(tmp) / "no-skill-md").mkdir()
            index = create_bar.skill_index([Path(tmp), Path(tmp) / "missing-root"], exclude="demo-skill")
        self.assertEqual(index, [("alpha-skill", "Use when alpha."), ("zeta-skill", "Use when zeta.")])


class CommandIndex(unittest.TestCase):
    def test_command_index_reads_description_and_stem(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "session-finalizer.md").write_text("---\ndescription: List the loose ends.\n---\n\nBody.\n")
            (Path(tmp) / "no-frontmatter.md").write_text("Just text.\n")
            index = create_bar.command_index(Path(tmp))
        self.assertEqual(index, [("no-frontmatter", ""), ("session-finalizer", "List the loose ends.")])

    def test_command_index_missing_root_is_empty(self):
        self.assertEqual(create_bar.command_index(Path("/nonexistent/commands")), [])


class BuildPrompt(unittest.TestCase):
    INDEX = [("git-workflow", "Use when committing."), ("secret-handling", "Use when a key leaks.")]

    def tool_input(self, **extra):
        ti = {"action": "create", "name": "demo-skill", "level": "global", "body": "BODY-TEXT here.",
              "reason": "REASON-TEXT", "evidence": "EVIDENCE-QUOTE from the session"}
        ti.update(extra)
        return ti

    def test_build_prompt_contains_parts(self):
        ti = self.tool_input(files={"references/notes.md": "NOTES-CONTENT"})
        prompt = create_bar.build_prompt(ti, self.INDEX, "RULESET-TEXT", "RUBRIC-TEXT")
        for part in ("RUBRIC-TEXT", "RULESET-TEXT", "git-workflow: Use when committing.",
                     "secret-handling: Use when a key leaks.", "demo-skill", "global", "BODY-TEXT here.",
                     "REASON-TEXT", "references/notes.md", "NOTES-CONTENT"):
            with self.subTest(part=part):
                self.assertIn(part, prompt)

    def test_build_prompt_truncates_files(self):
        ti = self.tool_input(files={"references/a.md": "æ" * 5000, "references/b.md": "ø" * 5000})
        prompt = create_bar.build_prompt(ti, self.INDEX, "RULESET-TEXT", "RUBRIC-TEXT")
        self.assertLessEqual(prompt.count("æ") + prompt.count("ø"), 6000)
        self.assertIn("[truncated]", prompt)
        self.assertIn("BODY-TEXT here.", prompt)

    def test_build_prompt_omits_evidence(self):
        prompt = create_bar.build_prompt(self.tool_input(), self.INDEX, "RULESET-TEXT", "RUBRIC-TEXT")
        self.assertNotIn("EVIDENCE-QUOTE", prompt)


class CallClaude(unittest.TestCase):
    def test_call_claude_sets_child_env(self):
        seen = {}

        def fake_run(argv, **kwargs):
            seen["argv"], seen["kwargs"] = argv, kwargs
            return subprocess.CompletedProcess(argv, 0, stdout='{"verdict":"allow"}', stderr="")

        original = create_bar.subprocess.run
        create_bar.subprocess.run = fake_run
        try:
            out = create_bar.call_claude("PROMPT", "claude-haiku-5-5")
        finally:
            create_bar.subprocess.run = original
        self.assertEqual(out, '{"verdict":"allow"}')
        self.assertEqual(seen["kwargs"]["env"]["AUTOHARNESS_CHILD_SESSION"], "1")
        self.assertEqual(seen["kwargs"]["timeout"], 60)
        self.assertEqual(seen["kwargs"]["input"], "PROMPT")
        argv = seen["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], "claude-haiku-5-5")
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--no-session-persistence", argv)
        # no CLAUDE.md, plugins or hooks: the judge sees only the prompt the eval measured
        self.assertIn("--safe-mode", argv)

    def test_call_claude_nonzero_exit_raises(self):
        original = create_bar.subprocess.run
        create_bar.subprocess.run = lambda argv, **kw: subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom")
        try:
            with self.assertRaises(RuntimeError):
                create_bar.call_claude("PROMPT", "claude-haiku-5-5")
        finally:
            create_bar.subprocess.run = original


if __name__ == "__main__":
    unittest.main()
