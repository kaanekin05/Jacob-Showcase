---
name: simple-localization-csv-rows
description: Use when editing a SimpleLocalization CSV table row.
category: localization
---

# SimpleLocalization CSV rows

A CSV row is only as durable as the Google Sheet behind it. Add every new key to the sheet in the same change, or the next `LocalizationSync` drops it.

- **Check the header first.** The first line is the language header (`Key;EN;TR;ES;...`). Count the `;` fields in the new row against it, and confirm each value sits under its language. Compare with `head -1 <csv> | tr ';' '\n' | nl` and the same pipe on the new row.
- **Keep the file's encoding and line endings.** Edit with a tool that preserves CRLF and the BOM state. Run `file <csv>` after the edit and compare with the pre-edit result.
- **Do not invent translations.** Leave a language cell empty when no translation exists. The runtime falls back to the English text and logs a warning. Report the empty languages so someone can supply them.
- **A row alone changes nothing on screen.** The label must point at the new key. For a text component with auto-localization off, set its localization key field to the new key in the scene or prefab. Confirm with `grep -n` on the serialized key and `git diff` on that file.
- **Packages with hard-coded text need no row.** If a third-party package holds its translations in code, a CSV row does not change its text.
- **Say where the change lands.** A scene or prefab edit reaches a device only in the next build, not the build already installed.
