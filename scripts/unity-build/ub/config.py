"""Per-game settings. The JSON files hold no secrets."""
import json
from dataclasses import dataclass
from pathlib import Path

GAMES_DIR = Path(__file__).resolve().parent.parent / "games"


@dataclass(frozen=True)
class Game:
    project_path: Path
    product_name: str
    dev_branch: str
    release_branch: str
    profiles: dict
    drive_folder_id: str
    mention: str
    xcode_major: int
    sdk_prefix: str
    team_id: str
    iphone_id: str
    session_paths: tuple
    regenerated_names: tuple
    merge_drivers: tuple
    guards: dict
    buildinfo_prefix: str
    keystore_env: tuple
    ota: dict | None = None
    # Unity 2022 and older have no Build Profiles. A static `Class.Method` in the game's Editor code builds
    # one profile instead, started with -executeMethod and given -ubProfile and -ubOut.
    build_method: str | None = None
    # Fixed APK file names, for a game whose Drive folders already use them: {"test": ..., "release": ...}.
    apk_names: dict | None = None

    @property
    def single_branch(self) -> bool:
        """Test and release build from one branch. The release has no merge."""
        return self.dev_branch == self.release_branch


def load_game(name: str) -> Game:
    data = json.loads((GAMES_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return Game(
        project_path=Path(data["project_path"]).expanduser(),
        product_name=data["product_name"],
        dev_branch=data["dev_branch"],
        release_branch=data["release_branch"],
        profiles=data["profiles"],
        drive_folder_id=data["drive_folder_id"],
        mention=data["mention"],
        xcode_major=data["xcode_major"],
        sdk_prefix=data["sdk_prefix"],
        team_id=data["team_id"],
        iphone_id=data["iphone_id"],
        session_paths=tuple(data["session_paths"]),
        regenerated_names=tuple(data["regenerated_names"]),
        merge_drivers=tuple(data["merge_drivers"]),
        guards=data.get("guards", {}),
        buildinfo_prefix=data.get("buildinfo_prefix", data["product_name"]),
        keystore_env=tuple(data["keystore_env"]),
        ota=data.get("ota"),
        build_method=data.get("build_method"),
        apk_names=data.get("apk_names"),
    )
