---
name: claude-code-plugin-mod-not-loaded
description: Use when a plugin command says its mod is not loaded.
category: troubleshooting
---

# Plugin mod not loaded: restart Claude Code, then re-run

When a plugin command answers with fallback text saying its mod is not loaded, the mod is not active in this session. Do not retry the setup in the same session.

1. Tell the user, in one sentence, that the mod is not loaded and that restarting Claude Code loads it.
2. After the restart, have the user run the same command again, for example `/effortless setup`.
3. A "hook was skipped" notice from a classic hook is informational. The `cc-plugin-sec-default` policy hook runs first. It is not a setup failure.

Do nothing else while the mod is unloaded. The fallback text is one instruction, so do not improvise a setup.
