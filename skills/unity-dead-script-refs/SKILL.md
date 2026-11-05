---
name: unity-dead-script-refs
description: Use when deleting Unity scripts, auditing which C# scripts are unused or dead before a migration, or when asked to delete dead references, missing scripts, or dead m_Script refs in prefabs and scenes.
category: unity-verification
---

# Unity dead script references

Scan for dead `m_Script` GUIDs after every deletion, before the commit. A GUID is dead when no live `.meta` defines it.

- Run `UNITY_BUILTIN=<Editor>/Contents python3 -I scripts/dead_refs.py <project-root>`. The script covers `Assets/`, `Packages/`, `Library/PackageCache/`, and the Editor's built-in packages. Use the same `UNITY_BUILTIN` on every run.
- Take the baseline before the change, then diff the sorted outputs. Compare only runs made with the same `UNITY_BUILTIN`. A different built-in path adds false positives, such as the legacy UI GUIDs.
- Each hit names the file, the component fileID, the GameObject, and the dead GUID. Fix every new hit in the same change. Retarget the `m_Script` block, or delete the component block and its `m_Component` entry. See `unity-yaml-editing`.
- Old projects can carry dead refs before your change. Record the baseline count and leave unrelated hits alone.
- Done means `comm -13 baseline after` prints nothing, which is no new hits. The total need not reach zero when the baseline already held hits. A deletion also lowers the total, because hits inside the deleted files go with them. In one wave the total fell from 1048 to 497 with zero new hits. Then compile-check with `unity-batchmode-run`.
- Removing a dead component also needs its button or event references cleared. See `unity-yaml-editing` Scenario 1.
- Before deleting a script as unreferenced, check four things. No `.unity`, `.prefab`, or `.asset` holds its GUID. No other C# file names its type. No entry point loads it by attribute or name (next bullet). No other script reads a `PlayerPrefs` key it wrote: grep the quoted key across `Assets`.
- Keep a zero-reference script when Unity or an SDK calls it by name. Examples are `[PostProcessBuild]` hooks in `Assets/Editor`, and the other half of a `partial` class that an SDK loads, such as SRDebugger's `SROptions.Game.cs`. A candidate scan that tags a file `HOOK` or partial means keep it.
- Candidate scan (read-only, no edits): grep every script GUID with `grep -roF -f guids.txt Assets ProjectSettings --exclude='*.meta' --exclude='*.cs'`. Then read each raw type-name hit by hand. Comments, method names that share the type name, and strings inflate the count. A type that appears only in comments is unused. Match the type name as a whole word. A substring hit inside a serialized field name is a false positive: a `PlayOn` search hits Unity's `m_PlayOnAwake` in prefabs. Read the field name before you count a hit.
- A binary `.prefab` or `.unity` file hides its GUIDs from grep. A candidate whose only neighbors are binary assets stays unverified, not delete.
- A type that live code calls but no scene or prefab GUID holds is never assigned. Its call path throws or does nothing. Report it as "referenced but obsolete" and leave the verdict to the user.
- A script held only by a non-build scene or prefab goes in the same change as that asset. Otherwise Unity shows Missing components.
- A script that serves an SDK being removed is "dead after migration", not "delete now". Remove its dependents in the same migration: its folder, its `PlayerPrefs` keys, and any post-build step that embeds the SDK. Remote Config keys follow §frameworks: stop client reads, never delete them server-side.
- Delete each script's `.meta` with the script. Remove a folder only once it is empty, and delete its `.meta` too.
- After a deletion batch, read each deleted `.meta`'s `guid:` line from HEAD with `git show HEAD:<path>`. Then grep `.unity`, `.prefab`, and `.asset` for every GUID and expect 0 hits. A name search misses GUID-only wiring, so the GUID grep is the check that counts.
