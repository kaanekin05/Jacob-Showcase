---
name: unity-build
description: Run the existing game build pipeline (Amber, Beryl, Coral, Dune, Ember, Fern) from chat, through scripts/unity-build/unity_build.py. Use for "build Amber release", "send a Coral test build", "build Ember test", "resume the stopped build", "ship to TestFlight", or a merge stop from that tool. This runs a pipeline that already exists. Writing Unity Editor tooling is the tools-programmer agent.
category: unity-verification
---

# Unity build pipeline

The script is the interface. Any agent, or a human in a terminal, can run `scripts/unity-build/unity_build.py` directly. This skill only adds the chat steps around it.

Configured games: `amber`, `beryl`, `coral` (Coral, g-coral) `dune` (Dune, g-dune), `ember` (Ember, g-ember) and `fern` (Fern, g-fern), in `scripts/unity-build/games/`. Run `unity_build.py <subcommand> --help` for the full command line.

## Single-branch games (`coral`, `dune`, `ember`, `fern`)

A game whose `dev_branch` equals its `release_branch` tests and releases from one branch, `development` for both. Settings change per build, not per branch. `ember` uses `chore/sdk-integration` for both.

- The release builds the tested commit as it is. It has no merge, so exit 3 never happens. Its first step, `head_guards`, checks HEAD against the game's release rules. A guard stop means a committed setting is wrong: fix it in a commit, run the test stage on it, then start the release again with `--discard-run`.
- The version bumps only after that version was released.
- Push commands name the one branch: `git -C <project> push origin development` (for `ember`, `chore/sdk-integration`). The repo stays on it after a release.
- `coral`, `dune` and `fern` are on Unity 2022.3, which has no Build Profiles. `ember` is on Unity 6 but has no Build Profile assets. Each config sets `build_method`, so Unity runs that game's build script in `Assets/Editor/Build/`: `CoralBuildPipeline.cs` for `coral`, `DuneBuildPipeline.cs` for `dune`, `EmberBuildPipeline.cs` for `ember`, `FernBuildPipeline.cs` for `fern`. The script holds the five profiles. It applies a profile's settings for one build, then restores them: SRDebugger, the `SR_ENABLED` or `DISABLE_SRDEBUGGER` define, Development Build, LZ4HC, AAB and Public symbols. A change to what a test or release build contains goes in that script.
- Signing passwords come from the env vars in the game's `keystore_env`, else the gitignored `Tools/keystore.local.json` in the game repo.
- A release profile rewrites three files that a test profile leaves alone: empty define entries in `ProjectSettings.asset`, and SRDebugger's `Resources.meta` and `UI/Prefabs.meta`. SRDebugger's disable and re-enable writes them. Commit them once on dev, and later builds leave them byte-identical. `dune` has them committed. A game without them stops after its first release build with those files named as foreign changes. Commit them, run the test stage, then start the release again with `--discard-run`.

Beryl also uploads its Addressables bundles to MinIO, after each platform's build. Test runs go to `development/`, releases to `production/`.

## Rules for every run

- Run the tool with Jacob (`/Users/kaan/Workspace/Jacob`) as the working directory, so session notes never land in the game repo.
- A build for both platforms takes about 30 minutes. Start `test`, `release` and `resume` with `run_in_background`, and wait for the exit.
- The tool never pushes and never posts to Slack. Both stay with the user.

## Test stage

1. Run `check <game> test`. Report any stop it prints, quoting the deciding line.
2. If it prints `Proposed version: X.Y.Z`, confirm that version with the user. Pass it as `--version X.Y.Z`.
3. Run `test <game> [--platform android|ios|both] [--version X.Y.Z]`.
4. On exit 0, tell the user to test on the phone. The Android test APK is already in the game's Drive folder `v<version>`. The release uploads it again only if it is gone. Do not start `release` until they say the build is good. That is the gate.
5. The test stage commits the version bump and its build outputs on dev. Give the push command for the user to run, for example `git -C <project> push origin dev`.

## Release stage

1. Run `check <game> release`. Report any stop it prints.
2. Collect the changelog in chat, one line per entry. Write it to a scratch file in the scratchpad directory.
3. Confirm with the user before the real run. Drive and TestFlight uploads are visible to others.
4. Run `release <game> [--platform ...] --changelog-file <file>`.
5. Pass `--allow-moved-dev` only when the user agrees to release although dev changed since the tested commit.

## Exit codes

- **0, success.** Show both Slack messages from `<game project>/Builds/v<version>/messages/`. The Android message is already on the clipboard. Print the `pbcopy` command for the iOS message. Then give the push command for the user to run, for example `git -C <project> push origin release`. Slack posting is manual by the user's choice.
- **1, a step failed.** Exit 1 always means a saved run, so `resume` is right. Quote the line that decided the failure. Fix the cause, then run `resume <game>`.
- **2, stopped before changing anything, or `resume` refused because the world changed.** Quote the deciding line. Report it, and let the user decide the next move.
  - A message starting "Stopped before the run started" comes with exit 2. No run was saved, so there is nothing to resume. Fix the cause and start the command again.
- **3, a merge needs the user's decision.**
  1. Show each conflict with both sides and a proposed resolution.
  2. Wait for the user's decision on each one.
  3. Apply it in the game repo with `git checkout --ours <path>`, `git checkout --theirs <path>`, or by editing the file. The merge runs on release, so `--ours` is release's side and `--theirs` is dev's. Then `git add <path>`, by explicit path.
  4. Run `resume <game>`.

  In `ProjectSettings/ProjectSettings.asset`, the tool has already resolved the version hunks. Edit only the conflict hunks that remain. Never run `git checkout --ours` or `--theirs` on that file, because that undoes the version hunks.

  When one side deleted the file, apply the user's decision with `git rm <path>` or `git add <path>`.

  The tool commits the merge itself. Leave the merge commit and `git merge --abort` alone unless the user chooses an abort. Keep the user's files.

## Release preflight and session notes

The release preflight stops when session files (the game's `session_paths`, for Amber `.memsearch/`, `.claude/autoharness/` and `.claude/skills/`) are uncommitted and differ on release. They would block the branch switch. Ask the user to commit them on dev first. Never discard them.

## Signing in to Drive again

If Drive sign-in fails, give the user only the safe two-step form. Run `! rclone config delete studio-drive`, then `! rclone config create studio-drive drive scope=drive > /dev/null`. Keep the `> /dev/null`. Tell the user to paste nothing back. Never suggest `rclone config reconnect`, because its fallback has the user paste an OAuth token into the chat.

## MinIO stops

- A sign-in failure on `studio-minio`: give only the steps the tool prints. The user runs `rclone config` in their own Terminal app, never through `!`, because the secret would reach the chat.
- "which this run did not upload": that production folder is live. Report it. Never delete, rename or overwrite it to get past the stop.
- "already exists with different content" on a bundle: report it with the file name. It points at a build problem, not a stale upload.

## After a release run

The game repo is left on the `release` branch. Tell the user.

## Discarding a run

`--discard-run` throws away an unfinished run, including a release run stopped inside its merge. Use it only after the user agrees. Say what is lost first, which the tool prints.
