---
name: bug-trace
description: "Trace a Unity C# bug from its entry point to its fault site by following the call/event/message chain through this codebase's decoupled indirection (event Action, UnityEvent, MessagePipe, SignalBus, VContainer DI, UniTask, Unity lifecycle, Animation Events). Prefers top-down from user input; switches to bottom-up when a stack trace exists. Gates on a red-capable repro loop, then traces statically and hands off instrumentation (it cannot live-step a running Unity process). Triggers: bug, crash, exception, stack trace, repro, regression, NullReferenceException, why does, where does, debug this, trace the call, follow the trail, who fires, who subscribes, what calls, find the cause, root cause, it doesn't work, unexpected behavior."
---

# Bug Trace

Systematically walk a bug from its **trailhead** (usually user input) along the live control-flow chain until you reach the **fault site** — the line that throws, or the point where actual behavior diverges from expected.

## Scope & honesty (read first)

- This is **static call-chain tracing by reading code** — Claude **cannot** set breakpoints or step a running Unity process. Where the trail forks or goes cold, hand the user **exact instrumentation** (`Debug.Log` / breakpoint placements) to run in their own Unity session and paste back. Claude does the reasoning; the user supplies the runtime truth.
- **Evidence over guess.** Every hop must be confirmed by a `grep`/`Read` hit with a `file:line`. Never assert a call edge you have not seen in the source. If you cannot resolve the next hop, say so and instrument instead of guessing.
- **A loop before a theory.** Reading code to build a theory before a repro exists is the failure this skill
  prevents. Phase 0 is the gate; it comes before any tracing. See §behavior root-cause and `karpathy-guidelines` section 4.
- **Read-only by default.** Trace and locate first. Per the master ruleset §behavior, **propose** the fix and wait for confirmation — do not edit while tracing.

## When this triggers

The user reports a crash, an exception with or without a stack trace, a feature that misbehaves, a regression, or asks "why/where does X happen" / "who fires/subscribes to Y".

## Phase 0 — Build the repro loop (gate)

**This phase is the skill.** With a loop that goes red on *this* bug, the trace, the fork narrowing and the
fix all just consume it. Without one, no amount of reading will settle anything. Spend disproportionate
effort here and refuse to give up early.

### Ways to construct one, roughly in this order

1. **EditMode test** against the pure-C# Model or Controller (§architecture). Fastest and fully agent-runnable — always try this first.
2. **PlayMode test** when the bug needs a scene, prefab wiring, or a Unity lifecycle order.
3. **A scripted repro** the user runs in the Editor, with `read_console` (or a pasted log) as the verdict.
4. **Replayed input.** Save the exact input sequence, message payload, or save-file state that triggers it, and drive it back through the same entry point.
5. **Differential run.** Same input against the last-good commit versus HEAD, diffing the output. Use when the bug is a regression with a known-good state.
6. **Repeat loop for flaky bugs.** Run the trigger 100× (or across frames) and count failures.
7. **Human-in-the-loop.** Last resort, when a human must click. Write the exact click sequence and the one observation you need back, so the user's run is still a structured verdict and not a story.

Prefer 1–2: they are deterministic and you can run them yourself. Anything from 3 down needs the user's Unity
session, so **propose it and wait** rather than driving the Editor unasked (§context MCP restriction, and the
read-only rule above).

### Tighten it

Once you have *a* loop, treat it as the product. Make it **faster** (narrow the test scope, skip unrelated
init), **sharper** (assert the user's exact symptom, not "didn't throw"), and **more deterministic** (seed
RNG, pin `Time`, avoid frame-count dependence, isolate scene state). A 30-second flaky loop is barely better
than nothing; a 2-second deterministic one finds the bug for you.

For a non-deterministic bug the goal is not a clean repro but a **higher reproduction rate**. A 50%-flake bug
is debuggable, 1% is not — keep raising the rate until it is.

### Minimise

Once it is red, shrink to the **smallest scenario that still goes red**. Cut inputs, callers, components,
scene objects, and config **one at a time**, re-running after each cut. Done when every remaining element is
load-bearing: removing any one of them turns the loop green.

This is not tidiness. Each thing you cut is a hop you will not have to trace in Phase 3, and what survives is
the regression test in Phase 6.

### The gate

Do not proceed to Phase 1 until you can name **one command you have already run** — and show its invocation
and output — that is:

- [ ] **Red-capable** — it drives the actual bug path and asserts the **user's exact symptom**. Not "compiles", not "doesn't throw".
- [ ] **Deterministic** — same verdict every run (for flaky bugs, a pinned high reproduction rate).
- [ ] **Fast** — seconds, not a full PlayMode boot where an EditMode test would do.
- [ ] **Runnable without a human**, or driven by an explicit written click sequence.
- [ ] **Red for the right reason.** If you forced the red by mutating code or a fixture, `diff` against a pristine copy to prove the mutation landed before you trust it.

**If you cannot build one, stop and say so.** List what you tried, then ask the user for one of: access to a
project state that reproduces it, a pasted Editor log or crash dump from a run that did, or approval to add
temporary instrumentation to a build. Do **not** start hypothesising without a loop.

**Exception:** a bug whose fault site is already given and unambiguous — a stack trace pointing at one line
you can read — may go straight to Phase 1 bottom-up. Say that you are skipping the gate and why.

## Phase 1 — Frame the bug and pick direction

1. **Capture the symptom precisely.** Exact exception type + message, or the concrete actual-vs-expected behavior. If the user has a **stack trace or logs**, ask for them — they collapse most of the search.
2. **Pick direction (auto):**
   - **Top-down (default/preferred):** start at the trailhead (user input) and follow forward. Use when there's no stack trace, or to confirm the path actually reached the suspected fault.
   - **Bottom-up:** start at the throw site / stack-trace frames and walk **up** to the cause. Use when a stack trace exists — jump to its top frame, then resolve each caller upward. Switch to top-down once you've localized the region, to confirm the trigger path.
3. State the chosen direction and why in one line before tracing.

## Phase 2 — Find the trailhead

Locate where the user's action enters code. In this codebase that is almost always:

- **New Input System** — `InputAction.performed/started/canceled` callbacks, `InputActionReference`, generated action-map classes. (Legacy `Input.Get*` is banned per §architecture — don't look for it.)
- **UGUI** — `Button.onClick`, `Toggle.onValueChanged`, `EventTrigger`, `IPointerClickHandler` etc. (UGUI is the default per §frameworks.)
- **Unity lifecycle / physics** — `OnCollisionEnter`, `OnTriggerEnter`, `Awake/Start/OnEnable` ordering for init-order bugs.
- **Animation Events** — string-named method invoked by the Animator; `grep` the method name to find the clip caller.

If the bug isn't user-triggered (timer, network, scene load), the trailhead is that event source instead.

## Phase 3 — Follow the trail through indirection (core)

At each step, identify the **next hop** and resolve it with a concrete search. This codebase is deliberately decoupled (§architecture and §frameworks), so the call graph jumps. Resolution recipes:

| Hop type | What you see | How to resolve the next hop |
|---|---|---|
| Direct call | `foo.Bar()` | Go to `Bar` definition. If `foo` is an interface, see VContainer row. |
| C# event | `OnX?.Invoke()` / `event Action` | `grep` for `OnX +=` and `OnX -=` to find every subscriber. |
| UnityEvent | `myEvent.Invoke()` / inspector-wired | `grep` `AddListener`; also check the prefab/scene `.unity`/`.prefab` for inspector wiring (persistent listeners). |
| MessagePipe | `publisher.Publish(new IFooMessage())` | Message is an **interface** (§frameworks). `grep` the interface name → find `ISubscriber<IFooMessage>` / `[MessageHandler]` / `.Subscribe(` handlers. |
| SignalBus (TheOne) | `signalBus.Fire<FooSignal>()` | `grep` the signal type → `Subscribe<FooSignal>` sites. (Events are classes, not structs, per §frameworks.) |
| VContainer DI | injected interface field / ctor param | The concrete type isn't at the call site. `grep` `builder.Register` / `Register<IFoo, FooImpl>` / `RegisterEntryPoint` to resolve interface → implementation, then trace into the impl. |
| UniTask async | `await SomeAsync(ct)` | Follow the awaited method. **Watch for fire-and-forget** `UniTaskVoid` / `.Forget()` — the trail branches and the caller does *not* wait; note it. Check `CancellationToken` paths — a cancel mid-chain can look like a "missing" effect. |
| Coroutine | `StartCoroutine(Routine())` | Follow `Routine`'s `yield` points; a `yield return` on a never-completing op stalls the trail. |
| Reflection / SendMessage | `SendMessage("X")`, `Invoke("X", t)` | `grep` the string-named method `X`. Flag as fragile. |

For each hop record: `№. file:line — hop type — symbol → next target`. When **multiple** subscribers/handlers exist for one event, you have a **fork**: narrow by evidence (types, conditions, active scene/prefab) or **ask the user which path their repro hits** rather than guessing.

## Phase 4 — Locate the fault

- **Top-down:** stop at the first hop where state or a branch produces the wrong value, a guard is missing, or the chain dead-ends before the expected effect (e.g. a `null` subscriber, an early `return`, a cancelled token, a `Forget()` that swallowed an exception).
- **Bottom-up:** the throw site is given; the *cause* is the first frame up the chain that passed bad state or violated a precondition.
- Confirm the fault with the actual offending lines, not a hypothesis. If runtime values are needed to confirm, go to Phase 5.

**When the trail does not hand you the fault outright, rank hypotheses before testing any of them.**
Write **3–5**, ordered, each with the prediction that would falsify it:

> *"If the `CancellationToken` is cancelled on scene unload, then holding the scene open past the await will make the effect appear."*

A hypothesis you cannot state a prediction for is a vibe — sharpen it or drop it. Generating one hypothesis
anchors you on the first plausible cause and the rest of the trace becomes confirmation-hunting; this is the
same reason §behavior/divergent says to push past the first three options. **Where
`superpowers:systematic-debugging` Phase 3 says "Form Single Hypothesis", this rule overrides it.**

Show the ranked list to the user before probing. They re-rank it instantly more often than not ("we changed
that prefab yesterday"). Don't block on it — proceed with your own ranking if they are away.

## Phase 5 — Instrumentation handoff (when the trail forks or goes cold)

When static reading can't determine which branch ran or what a runtime value was, produce a **copy-pasteable instrumentation set** for the user to run:

- Exact `Debug.Log` lines with `file:line` placement and a **run-unique** tag — pick four hex characters once per investigation and use them on every probe, e.g. `Debug.Log($"[bug-trace-a4f2] FooHandler hit, hp={hp}");` — wrapped in `#if UNITY_EDITOR` per §performance logging rules. The tag makes cleanup one `grep`: tagged logs die, untagged logs survive. A fixed `[bug-trace]` tag collides with the last investigation's leftovers; a per-run one does not.
- **Each probe must map to a specific prediction** from Phase 4, and you change **one variable at a time**. Never "log everything and grep".
- Or breakpoint locations (`file:line`) and which locals/fields to inspect.
- State exactly **what each log distinguishes** ("if A logs but not B, the message never reached the handler → registration bug").
- Ask the user to run the repro and paste output; resume the trace from the confirmed branch. Remind them to remove the temporary logs after (mention, don't leave orphan instrumentation).

## Phase 6 — Report and propose fix

Output:

1. **Symptom** — one line.
2. **Trail** — numbered hop list, each `file:line`, with fork points and how each was resolved (evidence or user confirmation).
3. **Fault site** — `file:line` + the precise reason actual ≠ expected.
4. **Proposed fix** — minimal and surgical (karpathy section 3): the smallest change at the fault site. **Do not edit yet** — present it and wait for the user's go-ahead. If the root cause implies a wider design issue (e.g. a `Forget()` swallowing exceptions across many call sites), name it but keep the proposed change scoped.
5. **Regression test, or the reason there is none.** The Phase 0 minimised repro is the test — propose it at the seam that exercises the **real** bug pattern as it occurs at the call site.

   **If no correct seam exists, that absence is itself the finding.** A shallow test at the wrong seam gives
   false confidence and is worse than none. Under §frameworks Testing, EditMode covers pure logic and PlayMode covers
   the scene, so a bug reachable only through a MonoBehaviour has no EditMode seam — and under §architecture that is an
   MVC finding (logic sitting in the View) rather than a testing problem. Report it as one.
6. **Verify before you claim done.** Re-run the Phase 0 loop against the original, un-minimised scenario; it must go green. Then `grep` the run tag from Phase 5 and confirm zero hits.

## Anti-patterns

- **DO NOT** trace, theorise, or propose a fix before Phase 0's loop goes red. No loop, no theory.
- **DO NOT** carry a single hypothesis into Phase 5 — rank 3–5 with predictions first, even when the first one feels obvious.
- **DO NOT** assert a call edge without a `file:line` you actually found — no imagined `Publish`→handler links.
- **DO NOT** silently pick one branch at a multi-subscriber fork — narrow by evidence or ask.
- **DO NOT** claim to have "stepped through" or "run the debugger" — you read code and hand off instrumentation.
- **DO NOT** start editing while tracing; locate first, propose second, edit only on confirmation (§behavior).
- **DO NOT** leave instrumentation logs in the report as if permanent — they're temporary diagnostics for the user to run and remove.
- **DO NOT** forget `UniTaskVoid`/`.Forget()` branches and cancelled `CancellationToken` paths — the most common "the call never had any effect" cause in this codebase.
