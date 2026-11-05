"""Version numbers in ProjectSettings.asset and the rules for when they move."""
import re
from dataclasses import dataclass

# [ \t]* and [^\r\n]* keep CRLF files intact.
_VERSION = re.compile(r"^([ \t]*bundleVersion:[ \t]*)([^\r\n]*)(?=\r?$)", re.M)
_ANDROID = re.compile(r"^([ \t]*AndroidBundleVersionCode:[ \t]*)(\d+)[ \t]*(?=\r?$)", re.M)
# The iPhone line inside the buildNumber block, not the one under applicationIdentifier.
_IOS = re.compile(r"(^[ \t]*buildNumber:[ \t]*\r?\n(?:[ \t]+(?!iPhone:)\S[^\r\n]*\r?\n)*?[ \t]+iPhone:[ \t]*)(\d+)", re.M)


@dataclass(frozen=True)
class Numbers:
    version: str
    android_code: int
    ios_build: int


def version_key(version: str) -> tuple:
    return tuple(int(p) for p in version.split("."))


def read_numbers(text: str) -> Numbers:
    v, a, i = _VERSION.search(text), _ANDROID.search(text), _IOS.search(text)
    missing = [n for n, m in (("bundleVersion", v), ("AndroidBundleVersionCode", a),
                              ("buildNumber/iPhone", i)) if m is None]
    if missing:
        raise ValueError("ProjectSettings.asset is missing: " + ", ".join(missing))
    return Numbers(v.group(2).strip(), int(a.group(2)), int(i.group(2)))


def apply_numbers(text: str, n: Numbers) -> str:
    read_numbers(text)  # raises if a field is missing
    text = _VERSION.sub(lambda m: m.group(1) + n.version, text, count=1)
    text = _ANDROID.sub(lambda m: m.group(1) + str(n.android_code), text, count=1)
    return _IOS.sub(lambda m: m.group(1) + str(n.ios_build), text, count=1)


def next_numbers(dev: Numbers, release: Numbers) -> Numbers:
    """One patch above the higher version; each build number one above its higher value.

    An iOS build number of 0 on both branches stays 0. A game that keeps iOS at 0 relies on App Store
    Connect needing a build number unique per version only, so 1.1.1 (0) and 1.1.2 (0) can both upload.
    """
    top = max(version_key(dev.version), version_key(release.version))
    ios_top = max(dev.ios_build, release.ios_build)
    return Numbers(".".join(map(str, (*top[:-1], top[-1] + 1))),
                   max(dev.android_code, release.android_code) + 1,
                   0 if ios_top == 0 else ios_top + 1)


def needs_bump(dev: Numbers, release: Numbers, record) -> bool:
    """False means a retest: keep the version and the build numbers."""
    d, r = version_key(dev.version), version_key(release.version)
    if d > r:
        return False  # dev is ahead of release
    if d < r:
        return True  # release moved on its own; dev never held that version
    # Equal: the merge made them so. Keep it until a release run has finished for it.
    return dev.version in record.released
