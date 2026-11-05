"""Subprocess seam: every external command goes through a Runner so tests can fake it."""
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Result:
    code: int
    out: str = ""
    err: str = ""


@dataclass(frozen=True)
class Call:
    cmd: list
    cwd: Path | None = None
    env: dict | None = None
    input: bytes | None = None


class Runner:
    def run(self, cmd: list[str], cwd: Path | None = None, env: dict | None = None,
            input: bytes | None = None) -> Result:
        p = subprocess.run(cmd, cwd=cwd, env=env, input=input, capture_output=True)
        return Result(p.returncode, p.stdout.decode("utf-8", "replace"),
                      p.stderr.decode("utf-8", "replace"))


class FakeRunner:
    """Records calls. Returns scripted results in order, then Result(0) once they run out."""

    def __init__(self, results: list[Result] | None = None):
        self.calls: list[Call] = []
        self._results = list(results or [])

    def run(self, cmd: list[str], cwd: Path | None = None, env: dict | None = None,
            input: bytes | None = None) -> Result:
        self.calls.append(Call(list(cmd), cwd, env, input))
        return self._results.pop(0) if self._results else Result(0)
