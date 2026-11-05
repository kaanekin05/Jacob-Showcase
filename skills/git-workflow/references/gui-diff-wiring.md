# External diff tool wiring for git GUI clients: detail

A terminal diff tool does not open from a git GUI as-is. Wrap it, test the wrapper by hand, and only then write any config.

- A GUI app starts the external tool with no terminal attached. A TUI tool then prints to nowhere. The wrapper must open a terminal window and run the tool there. Reuse an existing terminal when one is present, so CLI `git difftool` stays quiet.
- Copy `$LOCAL` and `$REMOTE` into a fresh temp directory before the wrapper returns, keeping each file's extension. Tools pick their language from the extension. Whether a GUI app deletes the originals early is unverified. The copy removes the question.
- Fork (macOS and Windows only): set Preferences, then Integration, then External Diff Tool, then Custom. Its binary holds the keys `externalDiffToolCustomPath` and `externalDiffToolCustomArguments`. Set the value once in the UI and read it back. Do not write those keys blind.
- SourceGit has no custom entry in its tool list. Route through its first entry, "Use Git Settings", which reads git's `diff.tool` and `difftool.NAME.cmd`. That also changes what `git difftool` does in a terminal.
- Before any config, open a `.cs` file and a `.png` through the GUI. Confirm the window opens and the temp copy still exists when the tool reads it.
- A structural diff tool that does not know a file type falls back to a plain line diff. Unity `.prefab` is one case. Renaming a prefab to `.yaml` made output worse, so keep the real extension. Route Unity YAML layout questions to `unity-yaml-layout-diff`.
