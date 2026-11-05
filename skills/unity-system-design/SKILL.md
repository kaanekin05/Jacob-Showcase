---
name: unity-system-design
description: >-
  House rules for seven Unity subsystem-design areas the master ruleset is silent on —
  save/persistence, telemetry/analytics, animation state machines, AI/NPC behavior,
  physics-as-gameplay, multiplayer netcode, and game feel. Use BEFORE designing or writing any of
  these. Triggers: save/load, persist progress, PlayerPrefs, serialize game state,
  migration, analytics event, telemetry, log an event, Animator state, animation
  transitions, cancel window, enemy AI, NPC behavior, behavior tree, FSM, pathfinding,
  collision response, trigger/collider gameplay, raycast hit reaction, netcode,
  multiplayer, replication, client prediction, authority, game feel, juice, screen
  shake, hitstop, impact feedback, squash and stretch, camera shake. Jacob-native, Unity 6 / C# 9,
  UniTask + VContainer + MessagePipe aware; honors §naming naming, §performance perf, §architecture MVC-strict.
---

# Unity System Design (house rules)

Six subsystem areas the §-ruleset does not cover at the code level. This skill is the **design checklist + the Jacob house rule** for each — consult the relevant section *before* writing that subsystem, then implement against source + `references/` for exact signatures.

**Scope.** The target projects are **single-player casual mobile** (Adjust, Firebase/Remote Config, GPGS, Ads, YooAsset). Sections 1–5 apply to that stack today. **Section 6 (netcode) is dormant** — author against it only when a project actually has a multiplayer case; do not build networked scaffolding into a single-player game "for later" (§behavior YAGNI).

**How this maps to the ruleset.** Every rule below is an *application* of an existing §-rule to a subsystem, not a new axis: persistence obeys §architecture (Model is pure C#, no `UnityEngine`), events obey §frameworks (MessagePipe interfaces / SignalBus no-structs), all hot paths obey §performance (no per-frame alloc). Where a section conflicts with a per-project override (e.g. `[[no-editor-log-guards]]`), the override wins.

---

## 1. Save / Persistence

**Applies when:** save/load, persist progress, checkpoint, PlayerPrefs beyond a single flag, serialize game state, cloud save, migration.

**House rules:**
- **Persist a plain DTO, never a live object.** The saved shape is a pure-C# serializable record — never a `MonoBehaviour`, never a Model instance with lifecycle flags, never anything holding a `UnityEngine` reference. This is §architecture Model-is-pure-C# applied to disk: the Controller maps Model → save-DTO → Model, the same way it maps Model → view-data.
- **Version from v1, always.** Every save schema carries an explicit `int Version` from the first ship. No unversioned save ever exists. A build that reads a save older than its own runs forward-only migrations (`v1→v2→v3`), never branches on "if field missing."
- **A failed read is corruption, not an exception to swallow.** Wrap load in a total function: parse failure / missing file / out-of-range version → return a well-defined fallback (fresh state or last-good backup), never crash, never half-apply. Write to a temp file then atomic-rename so a mid-write kill can't destroy the prior save.
- **Separate "what must persist" from "what is reconstructable."** Persist authored/earned state (progress, currency, unlocks, settings). Never persist derived runtime state you can rebuild on load — it bloats the save and creates migration debt.
- **Serialization choice:** JSON via `JsonUtility`/Newtonsoft for human-debuggable saves; a schema format (MessagePack/Protobuf) when size or tamper-resistance matters. Decide once per project; don't mix.
- **Test gate:** a round-trip test (write → read → equal) and at least one *old-version-load* test per shipped schema bump. Save compat is a release gate, not a feature test. An atomic-write test must truncate the temp file or kill the write mid-flight. A mocked exception is not a crash.

**Failure modes:** unversioned saves; persisting a MonoBehaviour/Model directly; treating a corrupt read as a hard exception; non-atomic writes that a crash can truncate; migration logic scattered per-field instead of one forward chain.

Related: `[[cross-game-shared-layer-gotchas]]` (shared-layer save bugs are latent in all games). Reviewer: `unity-reviewer`.

---

## 2. Telemetry / Analytics

**Applies when:** analytics event, telemetry, log an event, funnel, Adjust/Firebase event, A/B assignment, dashboards.

**House rules:**
- **Version every event schema; document the payload.** An event is an append-only contract, exactly like Remote Config keys (§frameworks): never mutate/rename/repurpose a live event's meaning or a shipped build's data goes silent-wrong — add a new event. Keep a per-project event registry (name → fields → owner → first-shipped version).
- **Route by environment and consent.** Editor/dev builds must not pollute production dashboards; gate emission on build config and on the user's consent state. No PII in event payloads — hash or drop.
- **Instrument stable behavioral boundaries, not noise.** Emit on meaningful state transitions (level_start, level_complete, purchase, retention_ping), not on every tap. Each event must answer a question someone will actually look at.
- **Fire-and-forget on a background path.** Telemetry never blocks gameplay and never allocates on the frame it fires from a hot path — queue + flush via UniTask off the game loop (§performance). A dropped event is acceptable; a dropped frame is not.
- **Dedup + timing discipline.** Guard against double-fire on ret/resume; timestamp at emission, not at send.

**Failure modes:** renaming/repurposing a live event (breaks historical funnels); PII in payloads; instrumenting low-value clicks; synchronous send on the game loop; dev events reaching prod dashboards; no schema version so consumers can't tell old from new.

Related: `[[cross-game-shared-layer-gotchas]]`, `[[gpgs-internal-test-build-checklist]]` (shipped-placeholder trap has an analytics cousin — verify event ids are real before an internal build).

---

## 3. Animation State

**Applies when:** Animator state machine, animation transitions, cancel window, hit reaction, equip/stun/interrupt, blend tree, root motion vs gameplay.

**House rules:**
- **Gameplay truth ≠ presentation timing.** The Model/Controller owns whether the character *is* attacking; the Animator owns how it *looks*. Never read game state off `Animator.GetCurrentAnimatorStateInfo` and never put damage/state-transition logic in an Animation Event callback beyond forwarding a signal (§architecture: no game logic in a MonoBehaviour/View).
- **Kill state explosion with grouping + priority.** Don't create N² transitions. Group by category (locomotion / action / reaction), assign an interrupt priority, and drive transitions from a small explicit set of parameters — not a web of bool-to-bool `Has Exit Time` links.
- **Every action needs its edge cases enumerated:** interruption, stun mid-action, equip swap during animation, hit-react cancel, and cancel windows (which frames accept the next input). Design these *before* wiring the Animator, or they surface as "stuck in animation" bugs.
- **Hash, never string.** `Animator.StringToHash()` for every parameter/state id, cached — never raw strings in the loop (§performance).
- **Animation Events forward, they don't decide.** An Animation Event calls into the Controller ("attack contact frame reached"); the Controller decides consequences. When you trace a bug, treat the event as one indirection hop.

**Failure modes:** reading gameplay state from Animator; logic inside Animation Event callbacks; transition explosion; missing cancel/interrupt handling; raw-string parameter lookups every frame.

Reviewer: `unity-reviewer`.

---

## 4. AI / NPC Behavior

**Applies when:** enemy AI, NPC behavior, behavior tree, FSM, utility AI, pathfinding, aggro, spawn director.

**House rules:**
- **Separate sense → decide → act.** Three distinct steps: gather world facts (sensing), choose an intent (decision model), execute it (action). Mixing them is why AI becomes un-debuggable. The decision layer is pure-C# and unit-testable without a scene (§architecture) — it takes a sensed snapshot, returns an intent.
- **Pick the structure for the complexity, not the fashion:** FSM for a few clear states, behavior tree when reactions compose, utility scoring when many factors trade off. Casual-mobile enemies are usually an FSM — don't reach for a BT library for three states (§behavior reduction ladder).
- **Tuning hooks + readable debug out.** Expose the knobs as `[SerializeField]`/ScriptableObject data (§architecture data-driven), and give every agent a debug readout of its current state/intent — opaque AI is untunable AI.
- **Handle fail states explicitly:** no valid path, target lost, stuck, off-navmesh → each needs a defined fallback, not undefined behavior.
- **Profile density early.** N agents each doing per-frame sensing/pathfinding is the classic mobile frame-killer — budget sensing frequency (tick AI at 5–10 Hz, not every frame), pool agents, and no per-frame LINQ/alloc in the decision loop (§performance).

**Failure modes:** sense/decide/act tangled together; BT/utility complexity for an FSM problem; hardcoded tuning; no debug visibility; unhandled navigation fail states; every-frame sensing at scale.

Reviewer: `unity-reviewer`, perf via `unity-performance`.

---

## 5. Physics as Gameplay

**Applies when:** collision response drives gameplay, trigger/collider logic, raycast hit reactions, force-based movement, physics-driven mechanics.

**House rules:**
- **Decide what is simulated vs authored vs faked — per mechanic.** Real rigidbody sim is expensive and non-deterministic; much "physics" in casual games is better faked (tween, kinematic move, scripted arc). Choose deliberately; don't simulate what a DOTween arc does cheaper and more controllably (§behavior rung 3: does a framework API already do it).
- **Forces/velocity in `FixedUpdate` only** (§architecture). Read input in `Update`, apply in `FixedUpdate`. Never mutate a Rigidbody from `Update`.
- **One owner for collision response.** Collision/trigger callbacks fire on the View (MonoBehaviour); they *forward* to the Controller, which owns the response — never compute damage/scoring inside `OnCollisionEnter`/`OnTriggerEnter` (§architecture). `CompareTag`, not `tag ==` (§performance).
- **Control update order + framerate sensitivity** where a mechanic depends on it; document any fixed-timestep assumption. Test extreme cases: high speed (tunneling → continuous collision detection), stacked contacts, zero/negative scale.
- **Debug tools for contacts/forces** — physics bugs are invisible without visualizing the contact points and force vectors.

**Failure modes:** simulating what should be faked (cost + nondeterminism); force application in `Update`; gameplay logic inside collision callbacks; tunneling at high speed with discrete detection; `tag ==` in trigger handlers.

Reviewer: `unity-reviewer`, perf via `unity-performance`.

---

## 6. Multiplayer Netcode (dormant — author when a project needs it)

**Applies when:** a project *actually* has multiplayer. Not before. Single-player casual games build none of this.

**House rules (for when the case exists):**
- **Define trusted authority first.** Decide server-authoritative vs host vs deterministic-lockstep before any replication code. Client is never trusted for anything score/economy/progression-affecting.
- **Choose replication + prediction per system,** not globally: state that tolerates latency (cosmetic) replicates differently from input-critical state (movement → client prediction + server reconciliation).
- **Design disconnect/reconnect/failure from day one** — mid-session drop, rejoin, host migration. These are not edge cases in networked games; they're the common path.
- **Profile bandwidth + state churn; plan cheat resistance, QA, and telemetry** as first-class, not bolt-on.
- **Starting numbers (tune per game):** design for 100–200 ms round-trip latency, not LAN. Keep packets under ~1,200 bytes to avoid IP fragmentation. Replicate continuous state (position) at 20–60 Hz and discrete state (health, inventory) only on change. Send each client only entities in its area of interest.
- **Never send what the client must not know.** Server validation stops speed hacks and item dupes; it cannot stop a wall hack if hidden enemy positions reach the client at all.

**Failure modes:** trusting the client; one-size replication; treating disconnect as an edge case; no bandwidth budget; building this into a game that has no multiplayer requirement (the biggest one).

---

## 7. Game Feel (juice)

**Applies when:** a mechanic is mechanically correct but lands without weight — hits read as bookkeeping, pickups vanish silently, the primary verb feels mushy.

**House rules:**
- **Apply the layers in this order; each depends on the one before it.** (1) Input latency — the primary verb must produce a visible response inside ~100ms. (2) Response curves — acceleration, easing, overshoot on the player's own motion. (3) Contact feedback — flash, squash, hitstop at the moment of impact. (4) Camera — shake, kick, FOV punch. (5) Audio-visual sync — sound on the same frame as the visual. No amount of juice hides a laggy control, so never start at layer 3.
- **Feedback that hides the next decision is a bug, not polish.** Shake, flash, and hitstop exist to clarify game state. If an effect obscures the thing the player must react to next, cut it or scale it down. Size the magnitudes so death and explosion are unmistakable while a pickup stays subtle.
- **Screen shake is trauma-driven, squared, and hard-capped.** Events add trauma; displacement is `trauma * trauma`, so small events barely move the camera and big ones snap. Decay trauma linearly per second and clamp it at 1.0 so stacked events cannot fling the camera. Shake with no decay, or constant ambient shake, is nauseating and hides the play field.
- **Hitstop scales the gameplay delta only.** Never freeze by stopping the render loop — the frame must keep drawing or the frozen moment is invisible. Feed the scaled delta to gameplay, and `Time.unscaledDeltaTime` to camera, tweens, and HUD so feedback stays live. Reserve it for heavy contact at 60–90ms; on every minor event the game reads as laggy rather than weighty.
- **Every event gets a named feedback stack, authored as data.** One event maps to several layers at stated magnitudes (§judgment — feel is a spec). Build them as atomic `MMF_Player` feedbacks (§frameworks Feel) or DOTween sequences, never as literals inside a MonoBehaviour. Feedbacks are View-layer: the Controller publishes the event, the View plays the stack (§architecture).
- **Vary repeated audio.** An identical sample replayed at the same pitch reads as machine-gun fire. Vary pitch by roughly ±6% per playback, and duck ambience while hitstop holds so the impact reads.
- **Route effect randomness through the injected RNG, not `UnityEngine.Random`.** Shared static randomness breaks replays, deterministic tests, and any seeded repro.

**Reference stack (starting numbers, tune per game):** pickup → pop + HUD counter punch + pitch-varied chime + 0.15 trauma · player hit → 70ms hitstop + 0.4 trauma + emissive flash + rumble + HUD pulse · enemy killed → 40ms hitstop + 0.3 trauma + flash · boost/dash → +6° FOV punch + 1.15 stretch + whoosh · jump/land → stretch on takeoff, 0.9 squash on landing · explosion → 90ms hitstop + 0.7 trauma + full-screen flash + heavy rumble.

**Failure modes:** juicing layer 3 while layer 1 is still broken; trauma added without the square curve or the cap; hitstop on every minor event; feedback that gates the primary verb behind an animation finishing; effects driven by the scaled delta so they desync during hitstop; emissive flash on a material whose `emissive` color is black; per-frame allocation in shake or tween code (§performance); gameplay logic living inside an `MMF_Player` (§frameworks).

Reviewer: `unity-reviewer`, perf via `unity-performance`. Design-side numbers belong in `game-design-docs` section 7, Tuning Knobs.

---

## Notes

- Self-contained: this skill carries its own detail; it does not route elsewhere for the rules.
- Keep aligned with the master ruleset — if a section starts duplicating a §-rule verbatim, cut it here and point at the §. These are *extensions*, not restatements.
- Provenance: the six-topic gap map was surfaced by comparing Jacob to `everything-game-dev-code` (MIT); the checklists there were generic — this content is Jacob-authored against the actual stack. That upstream is watch-only in `check-updates.sh` section 7.
- Provenance: section 7, Game Feel, was surfaced by comparing Jacob to `threejs-game-skills` (MIT), whose `game-feel.md` is TypeScript against a WebGL renderer — the layer ordering, the readability rule, and trauma-squared-with-a-cap are the portable half; the Unity form here is Jacob-authored against Feel, DOTween, and §performance, §architecture and §frameworks. That upstream is watch-only in `check-updates.sh` section 7.
- Provenance: section 6's starting numbers and the hidden-data rule were harvested 2026-09-14 from the archived `game-developer` (Jeffallan) and `game-development-sickn33` skills; their code samples were rejected.
