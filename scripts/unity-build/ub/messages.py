"""Slack message templates (exact copy from the spec) and the clipboard hand-off."""
import os

from .config import Game
from .runner import Runner


def _changelog(lines) -> str:
    if isinstance(lines, str):
        lines = lines.splitlines()
    out = []
    for raw in lines:
        for line in str(raw).splitlines():
            line = line.strip()
            if line:
                out.append("-" + line.lstrip("-"))
    return "\n".join(out)


def android_message(game: Game, ver: str, links: dict, names: dict, changelog) -> str:
    return (
        f"{game.product_name} Android v{ver} Drive'a yüklendi hocam {game.mention}\n"
        "\n"
        f"Drive Folder: {links['folder']}\n"
        f"Test APK: {names['test_apk']}\n"
        f"Release APK: {names['release_apk']}\n"
        f"AAB: {names['aab']}\n"
        f"Symbols: {names['symbols']}\n"
        f"BuildInfo: {links['buildinfo']}\n"
        "\n"
        "Changelog;\n"
        f"{_changelog(changelog)}"
    )


def ios_message(game: Game, ver: str, links: dict, names: dict, changelog) -> str:
    return (
        f"{game.product_name} iOS v{ver} TFye yüklendi hocam {game.mention}\n"
        "\n"
        "Changelog;\n"
        f"{_changelog(changelog)}\n"
        "\n"
        f"Drive Folder: {links['folder']}\n"
        "dSYMs: dSYMs.zip\n"
        f"BuildInfo: {names['buildinfo']}"
    )


def copy_to_clipboard(text: str, runner: Runner) -> None:
    # pbcopy garbles non-ASCII (ü, ı) without a UTF-8 locale.
    # LC_ALL would override LC_CTYPE, so it is dropped.
    env = {k: v for k, v in os.environ.items() if k != "LC_ALL"}
    env["LC_CTYPE"] = "UTF-8"
    result = runner.run(["pbcopy"], env=env, input=text.encode("utf-8"))
    if result.code != 0:
        raise RuntimeError(f"pbcopy failed (exit {result.code}): {result.err.strip()}")
