---
name: git-history-search
description: Use when checking git history for a deleted value or file, or when the user wants to view a repo's commits or diffs without fetching or downloading it.
category: git-workflow
---

# Git history search

Answer "was it ever in git?" by searching every ref and the removed file's last content, then report what you found. Two fruitless targeted lookups is the budget. After that, report "not found after searching the patterns used across N commits and M refs", never "absent".

1. Read the current tree first. An empty field now means the value is empty now. Only history can show whether it once had a value.
2. Search every ref, not just the checked-out branch. Run `git branch -a` and `git log --all --oneline | wc -l`. Remote-only branches can hold history the local branch lacks, so name them in the report.
3. Search content with the pickaxe: `git log --all -p -G 'regex' --format='COMMIT %h %ad %s' --date=short -- . ':!*.xml' ':!*.dll'`. Use `-G` to match changed lines by regex. Filter out doc comments and generated files before you read the hits, because a parameter doc comment matches a name without holding a value.
4. Search by path. Run `git log --all --name-only --format= -- 'glob'` to list every file that ever matched. Run `git log --all --oneline --diff-filter=D -- path` to find the commit that deleted it.
5. Read what a deleted file held. Run `git show SHA^:path` on the deleting commit's SHA. The parent commit holds the last content. Use `sed -n` to cut the window you need.
6. Report each hit with its SHA, date, and file, then say what the current tree holds. A hit that only shows the field was already empty is not a "had a value" hit.

Do not conclude from a single grep. Run step 2 before saying a branch lacks the value.

## Viewing a repo's changes without downloading it

When the user asks to see commits or diffs but not to fetch the repo, do not clone or fetch it. Pull only the one commit from GitHub:

- Size check first: `gh api repos/<owner>/<repo> --jq '.size'` (KB). Report it before any download.
- Changed files for one commit: `gh api repos/<owner>/<repo>/commits/<sha> --jq '.files[] | "\(.status)\t\(.filename)"'`.
- Diff text for one commit: `gh api repos/<owner>/<repo>/commits/<sha> --jq '.files[].patch'`.
- Web view: `https://github.com/<owner>/<repo>/commits` for history, `.../compare/<old>...<new>` for a range.

Do not use `git clone --filter=tree:0` to browse history in a GUI client. Fork reads objects through its own library, and a partial clone fails with `find obj <sha>` because Fork cannot fetch the missing objects. When a tool fails on missing objects, report the limit and ask. A full `git fetch --refetch` is a multi-GB download and needs the user's yes first.

This skill answers "was X ever here". For "what would a folder delete lose", use `sdk-replacement-audit`.
