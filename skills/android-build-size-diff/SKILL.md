---
name: android-build-size-diff
description: Use when an Android APK or build size jumped with no cause.
category: unity-verification
---

# Android build size diff

Compare the two archives before you blame code. Run `python3 -I scripts/apk_entry_diff.py OLD.apk NEW.apk`. Keep `-I`, so the interpreter does not load code from the APK's folder.

- Equal entry counts and totals mean the growth sits outside the zip entries. Read the `gap` lines. A gap is the byte run between one entry's end and the next entry's header.
- An entry whose compressed size moved shows as a `delta` row. Start with that entry.
- Copy the Unity build log aside before the next build. The next build overwrites it. The build info JSON has no size fields, so the APK itself is the only size record.
- Session evidence: a 24 MB jump between two builds of one version kept 2,697 entries and changed compressed contents by 17 bytes. The new APK held a 24,319,878-byte gap. Its cause was not confirmed in that session, so treat the gap as the lead, not the answer.
