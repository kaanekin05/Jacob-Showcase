"""List m_Script GUIDs in Unity YAML files that no live .meta defines.
usage: UNITY_BUILTIN=<Editor>/Contents python3 -I dead_refs.py <project-root> [yaml-file ...]
With no yaml files, scans Assets/ for .unity, .prefab and .asset files."""
import os, re, sys

root = sys.argv[1]
files = sys.argv[2:]
if not files:
    for d, _, fs in os.walk(os.path.join(root, "Assets")):
        files += [os.path.join(d, f) for f in fs if f.endswith((".unity", ".prefab", ".asset"))]

bases = [os.path.join(root, b) for b in ("Assets", "Packages", "Library/PackageCache")]
if os.environ.get("UNITY_BUILTIN"):
    bases.append(os.environ["UNITY_BUILTIN"])

live = set()
for base in bases:
    for d, _, fs in os.walk(base):
        for f in fs:
            if f.endswith(".meta"):
                with open(os.path.join(d, f), encoding="latin-1") as fh:
                    m = re.search(r"^guid: ([0-9a-f]{32})", fh.read(), re.M)
                if m:
                    live.add(m.group(1))

block = re.compile(r"^--- !u!(\d+) &(-?\d+)[^\n]*\n(.*?)(?=^--- !u!|\Z)", re.M | re.S)
for path in files:
    with open(path, encoding="latin-1") as fh:
        text = fh.read()
    blocks = [(m.group(1), m.group(2), m.group(3)) for m in block.finditer(text)]
    names = {}
    for cls, fid, body in blocks:
        if cls == "1":
            n = re.search(r"^  m_Name: (.*)$", body, re.M)
            names[fid] = n.group(1) if n else "?"
    for cls, fid, body in blocks:
        g = re.search(r"m_Script: \{fileID: -?\d+, guid: ([0-9a-f]{32})", body)
        if g and g.group(1) not in live:
            go = re.search(r"m_GameObject: \{fileID: (-?\d+)\}", body)
            owner = names.get(go.group(1), "?") if go else "?"
            print(f"{os.path.relpath(path, root)}: component &{fid} on '{owner}' -> dead script {g.group(1)}")
