# Jacob Framework-Specific Rules (Strict)

> **Read-before-coding companion to `AGENTS.md` §frameworks.** These are strict, always-obey rules,
> but each is *conditional on the library* — so the full detail lives here instead of in the
> always-loaded ruleset. **Before writing code that uses any library below, read its block here first**
> (the §context "Read Before Coding" gate; declare it in your §manifest Context Manifest). The ruleset's §frameworks keeps a
> one-line footgun index per library as an always-resident safety net; this file is the authority.
>
> Moved out of the ruleset body on 2026-07-11 during a token-density pass. No rule was changed.

---

## Architecture vocabulary — §architecture ↔ DDD

Reference glossary, not a rule. §architecture's strict MVC is the authority on how Jacob code is structured; this
table only translates those layers into Domain-Driven Design terms for when a design conversation,
external doc, or teammate speaks DDD. Nothing here changes §architecture — if the two ever disagree, §architecture wins.

| §architecture and §frameworks concept | DDD term | When it applies |
|---|---|---|
| Model class with identity | Entity | Has lifecycle, changes over time |
| Model class without identity | Value Object | Immutable, equality by value |
| Controller that owns Models | Aggregate Root | Consistency boundary |
| `event Action` / MessagePipe | Domain Event | Cross-aggregate communication |
| VContainer-injected data access | Repository | Collection-like interface |
| Stateless operation on a Model | Domain Service | Doesn't belong on an entity |

Harvested from NeoLabHQ/context-engineering-kit `plugins/ddd` 2026-08-26; moved out of the resident
ruleset 2026-08-27 (§agent-engineering — a lookup table consulted occasionally does not earn a per-turn cost).

---

## UniTask
- **Also read `references/UniTask_Documentation.md` before writing UniTask code.** This block lists footguns, not the API. Grep the doc for the type or method you use, then read that window. The §context table gates both files.
- Never use `System.Threading.Tasks.Task` or standard `Coroutine` unless explicitly required.
- Always `async UniTask` or `async UniTaskVoid` (fire-and-forget).
- Use `await UniTask.Yield(PlayerLoopTiming.Update)` instead of `yield return null`.
- Always pass `CancellationToken` — use `this.GetCancellationTokenOnDestroy()` to prevent leaks on destruction or Play Mode exit.
- **Where each applies (the "unless explicitly required" boundary):** UniTask for web requests, scene loading, and complex state machines. A plain `Coroutine` is acceptable *only* for simple visual timing/tweens tied to the game loop — a case where cancellation and return values don't matter. Anything that can outlive its GameObject or needs a result is UniTask.

## Input System
- **New Input System only** (`UnityEngine.InputSystem`). No legacy `Input.GetKeyDown()` / `Input.GetAxis()`.
- Read input in the View layer only (ruleset §architecture MVC) — an Input Action callback drives a Controller method, it does not mutate the Model.

## VContainer
- **Also read `references/VContainer_Documentation.md` before writing VContainer code.** This block lists footguns, not the API. Grep the doc for the type or method you use, then read that window. The §context table gates both files.
- Never use `FindObjectOfType` or Singletons (`Manager.Instance`).
- Constructor injection `[Inject]` for standard classes. Method/property injection for MonoBehaviours.
- Register entry points with `builder.RegisterEntryPoint<T>()`.

## MessagePipe
- **Also read `references/MessagePipe_Documentation.md` before writing MessagePipe code.** This block lists footguns, not the API. Grep the doc for the type or method you use, then read that window. The §context table gates both files.
- Use MessagePipe for pub/sub messaging between systems.
- Register with `builder.RegisterMessagePipe()`.
- Use `[MessageHandler]` attribute for receiving messages.
- Prefer interfaces for message types to allow decoupling (never concrete classes).

## TheOne Studio standards (when applicable)
- Prefer **VContainer/SignalBus** over Zenject; **TheOne.DI/Publisher** over raw DI.
- Do **not** use structs for SignalBus events.
- Use Data Controllers pattern — no direct data access.

## Addressables
- **ALWAYS** use `*Async` variants (`LoadAssetAsync`, `InstantiateAsync`, `LoadSceneAsync`). Non-Async forms are `[Obsolete]` in 1.22.3 and **removed** in 2.9.1.
- **ALWAYS** release every `AsyncOperationHandle` via `Addressables.Release(handle)`. Forgetting leaks the AssetBundle indefinitely — even after scene unload.
- **NEVER** call `WaitForCompletion()` on the main thread. On WebGL it is unsupported and throws. Use `await handle.Task` or the `Completed` event.
- `AssetReference.LoadAssetAsync<T>()` returns a handle released via `assetRef.ReleaseAsset()`, **NOT** `Addressables.Release(handle)`. Mixing causes double-release exceptions.
- In 2.9.1, `LoadSceneAsync` adds `SceneReleaseMode` (default `ReleaseSceneWhenSceneUnloaded`). To keep the bundle alive after additive scene unload, pass `OnlyReleaseSceneOnHandleRelease` and release the handle manually.
- Catalog update flow is strictly ordered: `CheckForCatalogUpdates` → `UpdateCatalogs`. In 2.9.1, `UpdateCatalogs(bool autoCleanBundleCache)` can auto-clean stale bundles in one call.
- **NEVER** destroy prefabs cached in Addressables.
- Deferred scene activation (`allowSceneActivation = false`, or loading without activating) stops progress at **0.9**, and the operation never reports done. Divide by 0.9 for a loading bar. While it waits, Unity's async-operation queue is stalled: a following `UnloadSceneAsync` does not start until activation is allowed.

## asmdef (Assembly Definitions)
- **ALWAYS** use asmdef for module boundaries. Separate Runtime, Editor, and Tests into distinct assemblies.
- **NEVER** let Runtime reference Editor asmdef. Editor can reference Runtime. Tests can reference both.
- Keep asmdef boundaries aligned with logical module boundaries — one asmdef per feature/domain, not per file.
- Use assembly references (`.asmref`) for cross-assembly dependencies, not direct folder references.
- Benefits: faster incremental compilation, enforced encapsulation, clearer dependency graph.

## Render Pipeline (URP / HDRP / BiRP)
- **Choose the pipeline first — a foundational, project-wide decision.** Materials, shaders, lighting, post-processing are pipeline-specific; switching later is a migration, not a setting.
- **URP (Universal):** the **default** for mobile, 2D, mid-tier, WebGL, Switch, cross-platform. Pick URP unless a concrete HDRP-only feature is required.
- **HDRP (High Definition):** high-end **PC / current-gen console only**. **NOT supported on mobile, WebGL, or Switch.** Justify only by visual goals the target hardware can deliver.
- **BiRP (Built-in):** legacy / asset-compatibility only. **Do NOT start new projects on BiRP.** Some features (e.g. Graphics Tiers, `Camera.onPostRender`) exist **only** in BiRP with no SRP equivalent — account for that when porting.
- **NEVER switch pipelines mid-project** without a dedicated migration pass — materials/shaders don't auto-port and silently render magenta/unlit.
- Post-processing and Feel feedbacks have **per-pipeline variants** — use the correct one.

## UI System
- **Choose the UI system per project context.** Consult `unity-ui-specialist` agent. UGUI (`UnityEngine.UI`) is the default for runtime gameplay UI; UI Toolkit is acceptable where justified (editor tools, complex data binding, CSS-like styling). Do **not** use UI Toolkit for gameplay UI without consulting `unity-ui-specialist`.
- Canvas render mode: Screen Space - Overlay for most cases. Camera mode only when UI must render behind/in front of 3D objects.
- Use `CanvasScaler` with Scale With Screen Size + Match Width Or Height (0.5) for responsive layouts.
- Pool UI elements that spawn/despawn frequently (damage numbers, floating text, tooltips).
- Use `TMP_Text` (TextMeshPro) for all text — never `UnityEngine.UI.Text`.
- **Button labels start with a verb** naming the action: `Send`, `Save draft`, `Delete run`. Never `OK`, `Yes`/`No`, or `Let's go!` on a consequential action. A confirmation button repeats the consequence, so the dialog is answerable without reading the body: "Delete this save?" offers `Delete save` and `Cancel`.
- **One capitalization policy per element type.** Pick sentence case or title case, then apply it to every instance of that type. Sentence case is the safer default. `Save Changes` beside `Discard changes` reads as a bug.
- **A multi-step flow uses one vocabulary throughout.** Pick `Continue` or `Next`, not both. Alternating synonyms makes players wonder whether the buttons differ.
- **Label a toggle for its ON state.** `Send read receipts`, never `Don't send read receipts` — the negative turns the toggle into a double negative.
- **Never assemble a sentence around a variable** (`"You have " + n + " new items"`). Word order changes per language, and the concat allocates. Use one templated string with proper pluralization, per the localization-key rule in `agents/unity-ui-specialist.md`.
- **An empty state says what the place is, how to fill it, and offers one next action** — not a bare "No results". Never park persistent information there; it vanishes the moment content exists.

## Testing
- **EditMode tests**: Pure logic, no scene required. Use for utility methods, parsers, data validation, math.
- **PlayMode tests**: Require scene context. Use for component behavior, physics interactions, input handling, coroutine/UniTask flows.
- **NEVER** put gameplay logic in tests — test behavior, not implementation.
- Use `UnityTest` attribute (IEnumerator) for PlayMode tests that need frame advancement.
- Use `UniTask`-aware test patterns for async flows — never mix `Coroutine` and `UniTask` in the same test.
- Test fixtures: one `[TestFixture]` per class under test. `[SetUp]` for per-test init, `[OneTimeSetUp]` for shared fixtures.
- **A test earns its place with four answers.** What observable behavior does it protect? What credible regression makes it fail? Why does existing coverage not already catch it? Does it need a production seam, such as a test-only `internal` member, flag or hook, that no production caller uses? Missing an answer means extend an existing test or drop this one. A test that needs a seam belongs at the real boundary instead. (Harvested from gstack `test-audit`, 2026-11-03.)
- **A player-visible change is not done until someone has looked at it.** Compiling proves the code loads. Tests prove the logic. Neither proves the text fits the box. Enter Play mode on the affected scene, capture with `ScreenCapture.CaptureScreenshot` through `execute_code`, then read the PNG and compare it to the acceptance criteria before claiming done.
- **Never judge UI from a `manage_camera` screenshot.** It leaves out Screen Space Overlay UI, despite what its schema says. `unity-mcp-execute-and-test` has the detail.
- **Subagents have no MCP access, so the dispatcher does this look** after the agent returns (§behavior/superpowers). If Unity MCP is down, report `NOT VERIFIED`, never done. Describe only an image you opened.

## Feel (More Mountains)
- **Also read `references/Feel_Documentation.md` before writing Feel code.** This block lists footguns, not the API. The doc is about 416 KB, so grep it for the feedback or type you use, then read that window. The §context table gates both files.
- Use **Feel** for game feel / juice — screen shakes, particles, haptics, audio feedbacks, post-processing flashes.
- Prefer **Feel over hand-rolled tween chains** for feedback sequences. Feel's `MMF_Player` is composable and inspector-driven.
- Split feedbacks into **atomic** MMF_Players (charge, jump, landing), not one giant feedback. More control, less logic coupling.
- Feel works on **all render pipelines** (BiRP, URP, HDRP). Post-processing feedbacks differ per pipeline — use the correct variant.
- **NEVER** put gameplay logic inside feedbacks — they are View-layer concerns only.
- Remove demo folders (`FeelDemos`, `FeelDemosURP`, `FeelDemosHDRP`) from production builds if unneeded.

## SRDebugger
- **Also read `references/SRDebugger_Documentation.md` before writing SRDebugger code.** This block lists footguns, not the API. Grep the doc for the type or method you use, then read that window. The §context table gates both files.
- Use **SRDebugger** for on-device debugging — console, profiler, runtime options tuning, bug reports.
- Set `Loading: Disabled` and manually call `SRDebug.Init()` when you need explicit control over the debugger lifecycle.
- Use `SROptions` partial class for runtime tuning. Split by category: `SROptions.Gameplay.cs`, `SROptions.Debug.cs`, `SROptions.Cheats.cs`.
- **ALWAYS** wrap SRDebugger API in `#if !DISABLE_SRDEBUGGER` — ship builds fully disable the debugger.
- Use `SRDebug.Instance.SetEnabled(false)` via Editor API before release builds (adds `DISABLE_SRDEBUGGER` define, renames resource folders).
- **NEVER** submit to source control while SRDebugger is disabled — causes rename/move churn. Disable locally for builds, re-enable before committing.
- Bug Reporter: acquire API key via Settings window (requires Asset Store invoice number + verified email).

## RayFire
- **Also read `references/Rayfire_Documentation.md` before writing RayFire code.** This block lists footguns, not the API. Grep the doc for the component you use, then read that window. The §context table gates both files.
- Prioritize pre-fragmentation over runtime fragmentation. Runtime/dynamic slicing only when explicitly required.

## Native 2D Sprite Atlas
- Always use `UnityEngine.U2D.SpriteAtlas` for sprite packing/retrieval.
- Fetch sprites at runtime via `spriteAtlas.GetSprite("spriteName")` — never load individual sprites from Resources.

## YooAsset (caveat)
- YooAsset 2.3.17 had a critical CRC-validation bug. If working with YooAsset, verify version and consult any local design notes.

## Remote Config (RC) — Backward Compatibility (Strict)
- **Treat RC keys as an append-only, versioned contract** — same backward-compat discipline as a public API surface. Shipped older builds keep reading the keys they were built against.
- **NEVER mutate an existing RC entry in place** when changing its meaning, type, or semantics — repurposing a live key crashes/misbehaves older clients.
- **ALWAYS introduce a brand-new key for a changed value — new on BOTH axes:** a new RC key name AND a new in-code usage/variable name. Old build reads the old key; new build reads the new key.
- **"Destroy the old one" = deprecate the code reference only** (stop using it in new code), **NOT** delete it from the backend. Leave the old key live indefinitely so older builds keep functioning.
- **NEVER delete or rename a live RC key any supported/shipped build still reads.** Only safe once no supported client version references it.
