"""Local run record per game, kept outside the repo, plus the content fingerprint."""
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def default_state_dir() -> Path:
    env = os.environ.get("UB_STATE_DIR")
    return Path(env) if env else Path.home() / ".local" / "state" / "unity-build"


@dataclass
class RunState:
    stage: str
    platform: str
    branch: str
    version: str
    step: str = ""
    done: list = field(default_factory=list)
    game: str = ""
    # What a resume needs: build start times, changelog, guard snapshot, numbers, Drive links.
    data: dict = field(default_factory=dict)


@dataclass
class Record:
    path: Path
    released: list = field(default_factory=list)
    tested: dict = field(default_factory=dict)
    uploaded_ios_builds: list = field(default_factory=list)
    run: RunState | None = None

    @classmethod
    def load(cls, game_name: str, state_dir: Path | None = None) -> "Record":
        path = (state_dir or default_state_dir()) / f"{game_name}.json"
        if not path.exists():
            return cls(path)
        d = json.loads(path.read_text(encoding="utf-8"))
        run = RunState(**d["run"]) if d.get("run") else None
        return cls(path, d.get("released", []), d.get("tested", {}),
                   d.get("uploaded_ios_builds", []), run)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"released": self.released, "tested": self.tested,
                "uploaded_ios_builds": self.uploaded_ios_builds,
                "run": asdict(self.run) if self.run else None}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)


def fingerprint(game, ref: str, runner) -> str:
    """SHA-256 of `git ls-tree -r <ref>` with session paths removed."""
    r = runner.run(["git", "ls-tree", "-r", "-z", ref], cwd=game.project_path)
    if r.code != 0:
        raise RuntimeError(f"git ls-tree {ref} failed: {r.err.strip()}")
    kept = [l for l in r.out.split("\0")
            if l and not l.split("\t", 1)[-1].startswith(tuple(game.session_paths))]
    return hashlib.sha256("\n".join(kept).encode("utf-8")).hexdigest()
