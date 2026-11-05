# Scoped git commits by path: detail

The procedure lives in one place: `commands/commit-slices.md` Step 4, where the repo has it. Read it and follow it, even when committing a single slice without running `/commit-slices`. It covers the stage-check-commit form, why `git commit -- PATHS` fails the pre-commit hook, and the zsh path-splitting trap.

Two facts that point does not repeat:

- A failed `git add` stages nothing. Retry with literal paths or an array. Nothing needs undoing.
- A failed staged-set check is different. The `git add` already ran, so the paths are staged. Re-running `git add -- DELETED_PATH` then fails with `pathspec ... did not match any files` and aborts the whole add. Do not re-add. Re-run the `--no-renames` check on the index as it stands, then commit.
- Build the slice with `git status --short -uall`, never the bare form. The bare form shows an untracked folder as one line, so a slice of 63 entries was really 86 files. Re-list with the same `-uall` command right before each commit. Hooks and other sessions write files between approval and commit, so a new file can appear mid-run. Leave every new untracked file out of the slices and name it in the report.
- **Summarizing a large dirty tree.** A raw `git status` of a Unity repo runs to hundreds of lines. Group it by status and top two folders first, with `git status --porcelain --untracked-files=normal`, then `awk` to count per status and folder. Use the grouped counts to plan slices, then list the files of each slice with `-uall`.
- Read each commit body against its diff before committing. Name the scope of the last verification run in the body. If code landed after that run, say so, and name what has not been compiled or tested. Every package or file the body names must be one the diff changed. Fix a wrong body before commit, because the rule forbids amending it after.
- Before `git commit`, check that the staged set equals the slice. Use `git diff --cached --no-renames --name-only`. Without `--no-renames`, a deleted path plus an added path with matching content shows as one rename, so only the new name is listed and a correct slice fails the check.
- A shell array of paths works. The failure is a plain zsh `$var` holding several paths, which zsh passes as one argument.
- **Slicing one file that holds two unrelated edits.** Path staging takes the whole file. Before hand-building index blobs, offer the user a single commit that carries both edits, and name the carried hunks in its body. Hand-splitting a large file is the riskier default, and the user chose the single commit when offered this choice. Build the index blob yourself: take HEAD's copy, replace only the target line from the working file, then point the index at the new blob. `git show HEAD:PATH | python3 -I SCRIPT_THAT_SWAPS_LINE_N | git hash-object -w --stdin`, then `git update-index --cacheinfo 100644,SHA,PATH`. Before you stage a rebuilt file, compare the last bytes of HEAD and the working file with `tail -c 2 FILE | od -c`. One attempt added a trailing newline to a file that had none, which turns a one-line slice into a whole-file diff. Confirm with `git diff --cached --numstat` (expected added and deleted counts) before `git commit`.
- To count the files that only looked changed (Step 1 of commit-slices), save `git diff-files --name-only` before `git update-index --refresh`, then diff it against the sorted `git status --short` paths: `sort before.txt | comm -23 - after.txt | wc -l`. Strip the two-character status prefix and the quotes from `git status --short` first, or paths with spaces will never match.
- **Checkpoints without moving HEAD.** When commits are banned but each task needs a reviewable diff, record a dangling commit built from a temp index seeded from the parent. HEAD, the branch, and the real index stay untouched. Stage by path only, never with `git add -A` or `commit -a`, even on the temp index. That keeps other sessions' hunks out.

  ```
  export GIT_INDEX_FILE="$(mktemp -u)"
  git read-tree "$PARENT"
  git add -- $PATHS
  TREE=$(git write-tree)
  unset GIT_INDEX_FILE
  CHECKPOINT=$(git commit-tree "$TREE" -p "$PARENT" -m "$MSG")
  ```

- Use checkpoints before ruling that per-task history is lost. When a plan wants one commit per task and the repo bans commits, a ruling that reviews a raw diff and leaves no history gives up what this method keeps. Build the checkpoints first, then record the ruling only if the checkpoint form fails.
- Set `PARENT` to the previous checkpoint, or to `git rev-parse HEAD` for the first one. Chain each checkpoint on the last. Keep each sha in the task ledger file, and create no ref for it. Review a task with `git diff "$PARENT" "$CHECKPOINT"`.
- If HEAD moves during the run, another session has committed. Re-pin the base to the new HEAD before the final review. Compare the review's file list with the plan. Any file outside the plan came from that other commit, so note it or leave it out.
- **Subagent-driven plans in a no-commit repo.** The subagent-driven-development skill reviews each task as `BASE..HEAD`, so the checkpoint chain is that base. Build the chain before dispatching task 1. In the dispatch prompt, override the implementer template's "Commit your work" step with "do not commit; list the files you changed". Snapshotting a few shared files is not a substitute. It cannot show a hunk a peer session wrote outside those files, and it skips the checkpoint step this section requires first.
- Checkpoints never carry into a real commit. When the user asks for one, commit by path from the real index.
- When a helper script builds its path list, avoid `mapfile`/`readarray`. macOS ships bash 3.2 at `/bin/bash`, which lacks both. Use a `while IFS= read -r f; do files+=("$f"); done < <(...)` loop, or run the script under a newer bash. Check the script runs before trusting its commits.
