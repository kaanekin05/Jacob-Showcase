#!/usr/bin/env python3
"""Build, test and release a Unity game.

Run from the Jacob root:
  python3 scripts/unity-build/unity_build.py test    <game> [--platform android|ios|both] [--version X.Y.Z] [--discard-run]
  python3 scripts/unity-build/unity_build.py release <game> [--platform android|ios|both] [--changelog-file PATH] [--allow-moved-dev] [--discard-run]
  python3 scripts/unity-build/unity_build.py resume  <game>
  python3 scripts/unity-build/unity_build.py check   <game> <test|release>

Exit codes: 0 success, 1 failed step, 2 stopped before anything changed, 3 merge needs a decision.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ub import stages  # noqa: E402
from ub.config import load_game  # noqa: E402
from ub.record import Record  # noqa: E402
from ub.runner import Runner  # noqa: E402

PLATFORMS = ("android", "ios", "both")
DISCARD_HELP = ("Throw away an unfinished run, including a release run stopped inside its merge. "
                "Prints what is lost.")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="unity_build.py", description=__doc__.split("\n\n")[0],
                                epilog="Exit codes: 0 success, 1 failed step, 2 stopped before anything "
                                       "changed, 3 merge needs a decision.")
    sub = p.add_subparsers(dest="command", required=True)

    t = sub.add_parser("test", help="Bump if needed, build the test profiles, install or upload, record the tested commit.")
    t.add_argument("game")
    t.add_argument("--platform", choices=PLATFORMS, default="both")
    t.add_argument("--version", help="The new version when a bump is needed (see `check <game> test`).")
    t.add_argument("--discard-run", action="store_true", help=DISCARD_HELP)

    r = sub.add_parser("release", help="Merge dev into release, build, upload to Drive and TestFlight, write messages.")
    r.add_argument("game")
    r.add_argument("--platform", choices=PLATFORMS, default="both")
    r.add_argument("--changelog-file", type=Path, help="One changelog line per line. Without it, a terminal prompt asks.")
    r.add_argument("--allow-moved-dev", action="store_true",
                   help="Release even though dev changed since the tested commit.")
    r.add_argument("--discard-run", action="store_true", help=DISCARD_HELP)

    s = sub.add_parser("resume", help="Continue the unfinished run after a failure or a merge decision.")
    s.add_argument("game")

    c = sub.add_parser("check", help="Read-only preflight. For test, also prints the proposed version.")
    c.add_argument("game")
    c.add_argument("stage", choices=("test", "release"))
    c.add_argument("--platform", choices=PLATFORMS, default="both")
    return p


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        game = load_game(args.game)
    except FileNotFoundError:
        print(f"STOP: No settings for game '{args.game}' in scripts/unity-build/games/.")
        return 2
    record = Record.load(args.game)
    runner = Runner()
    if args.command == "test":
        return stages.run_test(game, args.platform, args.version, runner, record, args.discard_run)
    if args.command == "release":
        changelog = None
        if args.changelog_file:
            try:
                changelog = args.changelog_file.read_text(encoding="utf-8")
            except OSError as e:
                print(f"STOP: Cannot read the changelog file {args.changelog_file}: {e.strerror or e}")
                return 2
        return stages.run_release(game, args.platform, changelog, args.allow_moved_dev, runner, record,
                                  args.discard_run)
    if args.command == "resume":
        return stages.resume(game, runner, record)
    return stages.check(game, args.stage, args.platform, runner, record)


if __name__ == "__main__":
    sys.exit(main())
