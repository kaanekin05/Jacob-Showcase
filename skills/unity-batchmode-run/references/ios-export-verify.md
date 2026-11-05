# iOS export verification, headless

Use this after a batchmode iOS export. Judge each step by its output, not by the console.

1. Export. Run the Unity binary with `-batchmode -nographics -projectPath "$PWD" -buildTarget iOS -executeMethod Namespace.Class.BuildIOS -sdkOut "$OUT/xcode" -logFile "$LOG"`. Then print the exit code. Pass on exit 0 and a log line such as `[SdkUpdate] Build iOS: Succeeded, errors=0`.
2. Pod resolution. `grep -E "could not find compatible|Pod installation" "$LOG" | sort -u`. Empty output means the pods resolved. A `could not find compatible versions for pod` line names the pod and both pins that clash. A `Found multiple specifications` line alone is a warning, not a failure.
3. Pinned versions. Grep `Podfile.lock` for the SDK pods you bumped, for example `^  - AppLovinSDK `, `^  - Firebase/Core `, and `^  - Adjust `. Compare each version with the catalog you planned against.
4. Swift Package Manager check. Count `repositoryURL` in `Unity-iPhone.xcodeproj/project.pbxproj`. For a CocoaPods-only build the count must be 0. A non-zero count next to a pod of the same name is a duplicate framework waiting to fail at link time.
5. Unsigned build. `xcodebuild -workspace Unity-iPhone.xcworkspace -scheme Unity-iPhone -configuration Release -destination 'generic/platform=iOS' -derivedDataPath "$DD" CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO build > "$XLOG" 2>&1`. Read `** BUILD SUCCEEDED **` or `** BUILD FAILED **`. Grep `error:` and `duplicate symbol` in the same log. A line that merely contains `error:` inside source text is not a real error.
6. Built artifact. Read the app `Info.plist` with `/usr/libexec/PlistBuddy -c "Print :FacebookAppID"` and `Print :GADApplicationIdentifier`. Then list `Frameworks/`. Each SDK should appear once. A static `.a` left next to its `.xcframework` risks duplicate symbols.
7. Pin fixes. A clash that names a vendor pod, such as GoogleAdsOnDeviceConversion, usually sits in a vendor dependency XML under `Assets/Editor`. Align the older pin there, XML-escape `>` as `&gt;`, then re-export. Re-run steps 1 to 5 from the start, because each export regenerates the Xcode project.
8. Clean up. The export writes build-info JSON and may rewrite tracked files. Restore those with `git checkout -- <path>` by explicit path, then check `git status --short` before the next commit.
