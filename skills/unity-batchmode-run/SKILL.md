---
name: unity-batchmode-run
description: Use when running Unity batchmode or headless builds.
category: unity-verification
---

# Unity batchmode runs

Decide a headless Unity run by its exit code and its log, never by the console.

- Compile check: run the Unity binary with `-batchmode -nographics`, `-projectPath` set to the project root, `-buildTarget` for the platform, `-quit`, and `-logFile` pointing outside the project tree. Pass only when the exit code is 0 and `grep 'error CS'` on the log prints nothing. Also grep the log for `Exception`. An import can exit 0 and still log a `UnityException`, so read each hit before you count the run as a pass.
- Language-server C# diagnostics are not a compile verdict. Before a package is imported, the editor shows CS0246 and CS0103 errors for every type from that package. Those are stale until the batchmode run says otherwise. Run the batchmode compile and trust its `error CS` count and exit code over the diagnostics panel.
- Compile one changed Editor script without a batchmode run: call Unity's bundled compiler, `<Unity.app>/Contents/NetCoreRuntime/dotnet <Unity.app>/Contents/DotNetSdkRoslyn/csc.dll @file.rsp`. The response file lists the references the script needs. Delete the previous output DLL first, so a stale file cannot fake a pass. Pass when no `error` line prints. The compiler is a plain process and starts no Editor, so an open Editor on the project does not block it.
- Run an Editor method: add `-executeMethod Namespace.Class.Method`. End that method with `EditorApplication.Exit(code)`, so the exit code carries the result.
- Do not end a background run with `; echo "unity_exit=$?"`. The tool then reports the echo's status, which is 0, not Unity's. Read the real result from the log's result line and from any `Aborting batchmode due to failure` line, which marks a failed run.
- Call a package API your code does not reference by reflection, such as the Google EDM `PlayServicesResolver` method `ResolveSync(bool)`. Log the returned bool, then read `git status` for the files it changed.
- Temporary helpers go under an Editor folder, opened with a `// TEMPORARY ... Never commit` line. Delete the folder and its `.meta` after the run, and check `git status` before the next commit.
- Long builds: start them in the background. Read the log when the run finishes, or when the user asks for progress.
- Import a `.unitypackage` headless: pass `-importPackage <file>` with no `-executeMethod`. The run quits on its own. Judge it by exit code and `error CS` as above. A filtered 11.5.0 SDK import finished in about 80 seconds.
- Before a run, list the open Editors with `pgrep -fl 'Unity.app/Contents/MacOS/Unity'` and read each `-projectPath`. An Editor on another project does not block the run. An Editor on this project does, so stop and ask.
- A `-buildTarget iOS` run leaves iOS as the active target. Run `-buildTarget Android` again before the user opens the Editor, or the Editor opens on iOS.
- Give each parallel run its own log file and build output folder, so one run cannot overwrite another. Separate paths do not let two runs share one project. Unity opens a project in one Editor at a time, so a second run on the same project waits for the first. Run runs on the same project in sequence.
- After a run that writes into the project, read `git status --short` and restore the build-generated noise before the next step. Also read `git diff --stat`. A Unity save can re-serialize unrelated scenes and prefabs to the newer YAML format, so a few-line change becomes hundreds of lines. Revert those files with `git checkout --`, then apply your intended edits as direct YAML changes, per `unity-yaml-editing`. A platform switch can rewrite `ProjectSettings`. Keep only the changes you made on purpose, and restore the rest with a script you can re-run. Name every file the run left modified in your report, even one you did not expect. In the episode that ran a compile after a deletion, `Assets/NuGet.config` showed as modified after the iOS compile and went unmentioned. Revert it unless you meant the change.
- iOS export: exit code alone is not enough. Check pod resolution, the SPM duplicate count, the unsigned `xcodebuild` result, and the built frameworks. The full command list and greps are in `references/ios-export-verify.md`.
