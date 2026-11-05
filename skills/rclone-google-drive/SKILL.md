---
name: rclone-google-drive
description: Use when configuring rclone for Google Drive, uploading builds or files to a Drive folder with rclone, or when an rclone Drive upload is slow.
category: general
---

# rclone for Google Drive

Configure one rclone remote with the `drive` scope, and address the target folder by its ID. Do not use `drive.file`: it sees only files rclone created, so it cannot see an existing folder.

- Install on macOS with `brew install rclone`. The Homebrew build has no `mount` subcommand, because mount needs FUSE. Use `nfsmount` if a mount is needed.
- An S3 or MinIO remote takes an access key and secret instead of a browser login. Never put them on a command line, `!` or not: the chat and shell history keep it. The user runs `rclone config` in their own Terminal app and types them at the prompts.
- Point an S3 remote at the S3 API host, not the web console host, which refuses S3 calls. If the endpoint sits behind Cloudflare, set `sign_accept_encoding = false` in the remote's advanced options. Cloudflare rewrites `Accept-Encoding`, and the signature then fails with `SignatureDoesNotMatch`.
- Sign in with a command the user runs in their own shell: `! rclone config create gdrive drive scope=drive > /dev/null`. Keep the `> /dev/null`. `config create` prints the finished config, OAuth token included, and `!` output lands in the chat. Tell the user to run it exactly as given and to paste nothing back. Confirm the sign-in yourself by listing the folder. See `secret-handling`.
- Never suggest `rclone config reconnect`. It is interactive, and its fallback asks the user to paste a token back. On an expired token, rclone's stderr can print that advice too. Drop any stderr line that contains `config reconnect`, and give the two-step sign-in instead: `! rclone config delete gdrive`, then the `> /dev/null` create command above.
- If a token reaches the chat anyway, it has a refresh token that does not expire. Have the user remove rclone's access at https://myaccount.google.com/connections, then run `! rclone config delete gdrive` and the sign-in command again.
- rclone's shared Google client ID is being retired during 2026, and rclone prints a NOTICE about it on every call. The shared ID is also throttled across all rclone users. A slow upload is the usual symptom, about 0.5 MB/s per file. Read that NOTICE before you blame the connection. The lasting fix is the user's own client ID from Google Cloud: https://rclone.org/drive/#making-your-own-client-id. Do not change the remote while an upload is running.
- Read the folder ID from the Drive URL, the part after `/folders/`. Then list the folder before asking the user anything about it: `rclone lsjson gdrive: --drive-root-folder-id FOLDER_ID 2>/dev/null`. The listing shows names and IDs, including the naming format of existing subfolders. Keep stderr out of the JSON, because that NOTICE breaks a JSON parse.
- Stat every local file before the first upload, and stop before any copy if one is missing. Reject two local files with the same basename in one batch, because both would land under one Drive name.
- Upload one file at a time with `rclone copyto LOCAL_FILE gdrive:TARGET_NAME --drive-root-folder-id FOLDER_ID`.
- Drive allows duplicate names, so list the target folder before every upload. Stop on a same-name file of a different size and ask the user. Never overwrite it. Delete it only when the user chooses deletion, and offer rename first. `rclone deletefile` moves the file to Drive trash, so it stays recoverable there. `lsjson` returns `Name`, `ID`, `IsDir`, `Size` and `ModTime`. Build URLs from `ID`.
- Before a real run, upload one small test file, read its ID back from `lsjson`, and delete only that file. Tell the user first, because anyone with folder access can see the test file while it exists.
- Stop before any call when the folder ID is blank. With no `--drive-root-folder-id`, rclone uses My Drive root and creates folders there. Put the flag on every rclone call, including the listing and the test upload.
- When a same-name file has the same size, compare MD5 before you call it the same. `rclone lsjson --hash` returns the hash inside a `Hashes` object. Confirm the key name once on a real file before you rely on it. If the hashes differ, stop and ask, as for a size mismatch.
