"""Output file names, matching what the games already produce."""
from .config import Game


def test_apk(game: Game, ver: str) -> str:
    if game.apk_names:
        return game.apk_names["test"]
    return f"{game.product_name}_v.{ver}_T.apk"


def release_apk(game: Game, ver: str) -> str:
    if game.apk_names:
        return game.apk_names["release"]
    return f"{game.product_name}_v.{ver}_R.apk"


def aab(game: Game, ver: str, code: int) -> str:
    return f"{game.product_name}-{ver}-v{code}.aab"


def symbols(game: Game, ver: str, code: int) -> str:
    return f"{game.product_name}-{ver}-v{code}-IL2CPP.symbols.zip"


def buildinfo(game: Game, ver: str, platform: str) -> str:
    return f"{game.buildinfo_prefix}_{ver}_{platform}_BuildInfo.json"
