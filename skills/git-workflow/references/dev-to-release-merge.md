# Merge dev into release in a Unity game repo: detail

Merge in one direction only: `dev` into `release`. Never merge `release` back into `dev`. Never push either branch unless the user asks.

Auto-resolve only these classes:

- **Version lines.** Take dev's number, and only when dev's number is not lower than release's. Compare numerically, so `0.1.10` beats `0.1.9`.
- **Tool session folders** (memory journals, autoharness request files). Keep release's copy.
- **Regenerated build outputs** (build-ID files, binary content-state files). Either side works. Take one and say which.

Resolve a version line only when every line in its hunk is a version line. A hunk that mixes a version line with another setting is a decision. A file with no conflict markers, or a hunk with no closing marker, is a decision too. A merge driver that gives up can leave a file with no markers, and an auto-resolver reads that as resolved.

Everything else is a decision. Stop, list each file in chat with its two sides in one line, recommend one side, and wait. Ask about one conflict at a time, in dependency order.

After the merge, check every setting that must differ between dev and release. Verify that:

- each release-only switch still has its pre-merge value
- no debug define appears in any platform's define list
- no debuggable flag appears in the Android manifest

A violation stops the release run. Name the file, the setting, and the before and after values. A check that cannot read its target is a violation too: a missing file, a missing settings block, or a key absent before the merge. Never report those as a pass. Run the checks before the merge commit, not after it.

Leave an undecided merge in place. Keep `MERGE_HEAD`, and never abort or reset it before the user decides. Commit the merge only after the checks pass. Stage it by explicit path, never with `git add -A` or `commit -a`. Find unmerged paths with `git ls-files -u`, not by scanning files for markers. In a merge into release, `--ours` is release's side and `--theirs` is dev's. A resume after a user decision checks that `git ls-files -u` prints nothing before the run continues. A staged merge is still reversible. A committed bad merge needs a destructive reset to undo.

Before any `git switch`, compare every dirty path against the target branch, including files whose only change is line endings. A build can rewrite line endings with no content change. Such a file still blocks the switch partway through a run when the target branch differs. Detect a line-ending-only change with `git diff --ignore-cr-at-eol --quiet -- PATH` exiting 0 while `git diff --quiet -- PATH` exits 1. Restore it with `git checkout -- PATH` only when the path was clean when the run started and has no content change.

Take the guard baseline from the remote-tracking ref, `git show origin/release:PATH`, never from the local `release` checkout. The local branch can already hold a merge from an earlier partial run, a hand merge, or a restart. A baseline read from it lets a bad merge pass the guards. Do not run `git fetch` inside the run. If `origin/release` is missing, stop with a violation. The tool never pushes, so no local action moves that ref.

Before a merge starts, refuse if `.git/MERGE_HEAD` exists and this run did not write it. Record the pre-merge `HEAD` and the expected `MERGE_HEAD` in the run state, and refuse when either differs. Preflight reports a merge in progress as its own stop. It never tells the user to commit that merge as a new release.

A retry merges the same dev commit that was tested. Record the tested dev commit in the run state at test time. Before every merge attempt, first or retry, compare dev's current tip with that record. If dev moved, stop with exit 2 and name both SHAs. Carry `--allow-moved-dev` over from the original command only when the user passed it there. Never let a retry quietly take dev's new tip.

A guard that pins a value, such as a profile ID, reads the pin from `origin/release`. Test the guard against that real value. A placeholder value makes every probe stop at the guard and proves nothing about the merge.

After the merge concludes, check the guarded files for edits against committed content before any build. Guards read committed content, not the working tree. An unstaged fix can otherwise reach the builds while `HEAD` keeps the bad value.
