---
name: unity-yaml-editing
description: "Hand-edit Unity serialized YAML (.unity scenes, .prefab, .asset, .meta, ProjectSettings/*.asset) when the Editor cannot do the job — repairing m_Script GUID/fileID references, removing Missing components, fixing .meta GUIDs, patching settings fields with no public API, and resolving scene/prefab merge conflicts per object block. Last resort, not a shortcut: if the Unity Editor or Unity MCP can reach it, use that instead. Triggers: missing script, missing component, broken prefab reference, m_Script, fileID, GUID, .meta, meta file, guid collision, prefab merge conflict, scene merge conflict, .unity conflict, hand-edit YAML, edit the prefab file directly, ProjectSettings field, collision matrix, the Editor won't open it, script renamed and references broke."
---

# Unity YAML — Safe Hand-Edit Rules

Operational guidance for directly editing Unity's serialized YAML text. Hand-editing is the
**last resort**, not a shortcut.

> Vendored from `Besty0728/Unity-Skills` (MIT) `skills/yaml-editing`, 2026-08-25. Adapted for
> Jacob: REST-protocol preamble stripped, upstream `/metacheck` + `/skillcheck` delegations
> inlined or dropped, routing re-pointed at Unity MCP.

## When to load — and when NOT

**Prefer the Editor first.** For normal object/asset work use Unity MCP (`mcp__CoplayMCP__manage_gameobject`,
`manage_prefabs`, `manage_scriptable_object`, `manage_scene`, `manage_asset`, `manage_editor`) — it keeps
serialization valid for you. Per §context, reach for those tools only when the user explicitly asks to
create or alter Unity assets.

**Only hand-edit YAML when the Editor cannot reach**, i.e. one of:

1. **Compile failure** — a script doesn't compile, so the Editor cannot deserialize the component.
   Editor and MCP APIs are unavailable; the YAML text is the only level left.
2. **`.meta` files** — no MCP tool touches `.meta`. GUID and importer fields live only in text.
3. **Hidden ProjectSettings fields** — many `ProjectSettings/*.asset` fields have no public API.
4. **Merge conflicts** — the Editor cannot perform a 3-way merge of `.unity` / `.prefab`.

If none of these apply, stop and use the Editor. Do **not** hand-edit YAML for convenience.

## Core concepts

- **Object block / anchor** — every serialized object is a block headed by `--- !u!<classID> &<fileID>`.
  `<classID>` is the Unity type id (`1` = GameObject, `4` = Transform, `114` = MonoBehaviour).
  `<fileID>` is the object's anchor, unique **within this file**.
- **GUID vs fileID**
  - **GUID** — asset-level identity, 32-char hex, stored in the asset's `.meta`. Identifies the whole
    asset (a script, prefab, texture…).
  - **fileID** — sub-object identity inside a file (a specific component, a specific MonoScript class…).
- **Serialized reference** — `{fileID: N, guid: H, type: T}`. `guid` is omitted for same-file
  references (`{fileID: N}`).
- **`m_Script`** — a MonoBehaviour points at its script via
  `m_Script: {fileID: 11500000, guid: <scriptGUID>, type: 3}`. `fileID: 11500000` is the conventional
  MonoScript fileID; `guid` is the `.cs` file's GUID from its `.meta`; `type: 3` means the reference
  targets an asset on disk. A wrong `guid`/`fileID` here is exactly what produces
  "missing script / missing component".

## Scenario 1 — Reference / fileID repair

**When:** a script was renamed or moved, so a prefab/scene `m_Script` `guid`/`fileID` no longer
resolves; or a compile failure left a component as Missing and you must locate, delete, or re-point
it at the YAML level.

**How:** read the script's current GUID from its `.cs.meta`. In the prefab/scene, find the offending
`m_Script: {fileID: 11500000, guid: ..., type: 3}` and set `guid` to the correct value (keep
`fileID: 11500000`, `type: 3`). To delete a Missing component, remove its whole
`--- !u!114 &<fileID>` block **and** the matching `{component: {fileID: <fileID>}}` entry under the
owner GameObject's `m_Component` list — leaving one without the other corrupts the file.

**Danger:** deleting the object block but not its `m_Component` reference (or vice versa) breaks the
GameObject; changing a `fileID` other objects reference orphans those references.

## Scenario 2 — .meta / GUID safety

**When:** a `.meta` GUID looks hand-written (risking a third-party collision), or you must edit an
importer field with no API.

**Pseudo-GUID heuristics** — a real GUID is uuid4 hex. Treat as suspect any GUID with:
consecutive hex runs (`0123456789abcdef`), an interleaved increment pattern, long repeated-character
runs, a literal `abcdef` sequence, or the wrong length (≠ 32 hex chars).

**How:** regenerate with `python3 -c "import uuid; print(uuid.uuid4().hex)"` — never write a GUID by
hand. **Before changing any GUID, grep the whole project for it** (`.asset` / `.prefab` / `.unity` /
`.meta`) and update every reference in the same change.

**Danger:** changing a GUID without updating every reference silently detaches assets.

## Scenario 3 — ProjectSettings patch

**When:** you need a `ProjectSettings/*.asset` field (YAML) with no public API — a specific physics
layer / collision-matrix entry, a hidden `QualitySettings` value.

**How:** confirm a clean git tree first, locate the exact field by key, change only its value, then
let Unity reload and re-serialize to validate. Confirm the change **round-trips** (Unity rewrites the
file the same way) rather than reverting or reformatting it.

**Danger:** guessing the encoding of collision-matrix or enum-backed fields silently breaks settings.
Always verify Unity accepts the value on reload.

## Scenario 4 — Merge conflict assistance

**When:** a `.unity` / `.prefab` carries Git conflict markers.

**How:** Unity YAML is line-mergeable because each object is an independent
`--- !u!<classID> &<fileID>` block. Resolve **per block**: for a block changed on only one side, take
that side; for a block changed on both, do a true 3-way merge of the conflicting fields. After
resolving, ensure every referenced `fileID`/`guid` still has a defining block.

**Danger:** blindly accepting `--theirs`/`--ours` drops objects added on the other side or leaves
dangling references. Never resolve by deleting whole conflict regions without checking the `fileID`
references inside them.

## Hard rules

- **Back up first** — confirm a clean git tree (or commit/stash) before any YAML edit, so you can
  diff and revert.
- **Don't touch structure unless repairing references** — change values only; never renumber or
  reorder anchors/`fileID`s unless reference repair is the explicit task.
- **Re-import to validate** — after editing, trigger a Unity reimport/reload and confirm no new
  errors and that the file round-trips.
- **GUIDs are uuid4, never hand-written.**
- **Dry-run before bulk edits** — grep the impact set first; know exactly how many references a
  change touches before making it.
- **Change a GUID → change every reference.** A GUID edit is not done until all referencing files are
  updated in the same change.

## Jacob Ruleset Compliance

- **§context** — Unity MCP tools only when the user explicitly asks to create/alter Unity assets. This skill
  is the fallback for when those tools *cannot* reach, not an alternative to them.
- **§context (unfamiliar-codebase row)** — Grep and Glob read `.cs` text, not GUID wiring. This skill is the
  only thing that resolves prefab, ScriptableObject, scene and `.meta` references.
- **§behavior** — root cause, not symptom: one broken `m_Script` GUID usually means a whole renamed/moved
  script's references broke. Grep every referencing file and fix the set, then record the
  `TWINS: searched <guid> → <N> sites: <files|none>; excluded <file> (<ground>|assumed)` line.
  Every exclusion names the ground you read, or says `assumed` — a prefab you decided does not
  reference the script is the one that silently keeps a broken GUID.
- **§commits** — `.meta` files in the diff must be noted in the commit body: whether a script was
  serialized, renamed, or had Inspector variables changed.
