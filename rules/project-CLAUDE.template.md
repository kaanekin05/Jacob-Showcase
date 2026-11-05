# <Project> — project facts

Jacob's master ruleset loads separately. This file holds only what is specific to this repo.
Fill every `<slot>` from the repo. Write `TODO: <question>` where only the user knows the answer.

## Identity
- Name: <name>. Other names found in the repo: <old names, product name, folder names>.
- Namespace: `<root namespace>`.
- Unity version: <version from ProjectSettings/ProjectVersion.txt>.
- Render pipeline: <pipeline and version>. Default asset: `<path>`.
- Target platforms: <platforms>.

## Layout
- Game code root: `<path>`. Assemblies: `<asmdef names>`.
- Framework root: `<path>`.
- Test assemblies: `<EditMode name>`, `<PlayMode name>`.
- Folders that hold customizable code inside the framework: `<paths, or none found>`.

## Reference projects
- TODO: <which sibling projects to copy from, and what to copy from each>

## Unity MCP
- Server: `<name>` at `<url>`. Defined in <scope: user, project, or local>.
- Before you say Unity is unreachable, read `mcpforunity://editor/state`.
- If the read fails, report the exact error and ask. Do not guess that the Editor is closed.

## Design source
- TODO: <Figma file key, link, and export scale such as 1x or 3x>
- Canvas reference resolution: <width x height, from CanvasScaler>.
- Candidate export folders found under Assets: `<paths, or none found>`.

## Git
- Working branch: `<branch>`. Remote: `<remote url without credentials>`.
- Push policy: TODO: <may the agent push, and to which branch>
- Other committers seen in the last 200 commits: <author names with counts>.

## Verify commands
- Compile check: <command or MCP call>.
- EditMode tests: <assembly name>. PlayMode tests: <assembly name>.
- Enter Play mode: <command or MCP call>.
