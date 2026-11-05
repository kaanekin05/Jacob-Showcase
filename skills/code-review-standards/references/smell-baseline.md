# Smell Baseline

Twelve design smells from Fowler's *Refactoring* ch.3, carried so a review still has something to say
when a file breaks no explicit Jacob rule. Each entry reads **what it is → how to fix**, plus a
**Not this** line wherever a Unity pattern that complies with §code looks like the smell but isn't.

Harvested from `mattpocock/skills` `engineering/code-review` (MIT), 2026-09-07. Unity anti-matching is Jacob's.

## Three rules bind this file

1. **The Jacob ruleset overrides the baseline.** Where §code endorse something a smell would flag, the
   ruleset wins and the smell is suppressed. §architecture MVC-strict and §performance's allocation rules both produce shapes
   that read as smells out of context. They are not.
2. **Every smell is a judgement call, never a violation.** Report it as "possible Feature Envy", and it goes
   under **Suggestions** in Phase 8. A smell never lands in **Required Changes** and never blocks a merge on
   its own. A §code breach can block; a smell cannot.
3. **Skip anything tooling already enforces.** Rider, the Roslyn analyzers, and the `.editorconfig` catch a
   share of this. Reviewing what a tool already fails is noise.

Phase 8's confidence rule still applies: score the finding, drop it under 80, and quote the lines.

---

## The twelve

**Mysterious Name** — a method, field, or type whose name doesn't reveal what it does or holds.
→ Rename it. If no honest name comes, the design is murky, and that's the real finding.
*This one is §naming's, not the baseline's.* §naming owns naming (2–4 words, one unique keyword, never a bare
`Manager` / `Helper` / `Utils`), and `theone-unity-standards` `references/csharp/quality-hygiene.md` has the
detail. Cite §naming and don't restate it here.

**Duplicated Code** — the same logic shape appears in more than one place in the reviewed set.
→ Extract the shape once, call it from both sites.
This pairs with §behavior's TWINS sweep: if you find the second copy, grep for the third before proposing the fix.

**Feature Envy** — a method that reaches into another object's data more than its own.
→ Move the method onto the data it envies.
**Not this:** a Controller reading and mutating its own Model. §architecture makes the Controller the Model's owner, and
the Model is deliberately a passive bag of state with no behaviour. That is the architecture, not envy.

**Data Clumps** — the same few fields or parameters keep travelling together, a type wanting to be born.
→ Bundle them into one type and pass that.
In Unity this usually wants a `readonly struct` or a ScriptableObject, not a class. Check §performance before proposing
a reference type on a path that runs per-frame.

**Primitive Obsession** — a primitive or string standing in for a domain concept that deserves its own type.
→ Give the concept a small type of its own.
**Not this:** `[field: SerializeField]` primitives that a designer tunes in the Inspector. §judgment requires feel
numbers to be reachable as data, and wrapping a float in a type a designer can't edit is a regression, not a
fix. Flag raw `string` keys instead — those want `Animator.StringToHash` or `Shader.PropertyToID` per §performance.

**Repeated Switches** — the same `switch` or `if`-cascade over the same type recurs across the reviewed set.
→ Replace with polymorphism, or one shared map both sites read.
**Weigh it against §performance before proposing.** Polymorphism per state adds an allocation and an indirection. On a
per-frame path a `switch` over an enum is often the correct call, and `unity-system-design` §Animation/FSM
covers when a state class earns its keep. Report the repetition; leave the choice to the author.

**Shotgun Surgery** — one logical change forces scattered edits across many files.
→ Gather what changes together into one module.
The Unity form of "one module" is an asmdef per feature or domain (§frameworks). If a change crosses three asmdefs,
the boundary is drawn in the wrong place.

**Divergent Change** — one file or module is edited for several unrelated reasons.
→ Split it so each module changes for one reason.
This is Single Responsibility from Phase 5, stated as a symptom you can see in `git log` rather than as a
principle. If Phase 7b already flagged the file for churn, check which reasons drove it.

**Speculative Generality** — abstraction, parameters, or hooks added for needs nothing has asked for.
→ Delete it. Inline it back until a real need shows.
This is §behavior's reduction ladder rung 1 arriving after the fact, and `karpathy-guidelines` calls the same thing
out under Simplicity First. An interface with exactly one implementer and no test double is the usual tell.

**Message Chains** — long navigation the caller shouldn't depend on.
→ Hide the walk behind one method on the first object.
The Unity form is `transform.parent.GetChild(0).GetComponent<Foo>()`, and it breaks the moment someone
reorders the hierarchy. It also usually means the dependency should have been injected (§frameworks VContainer) or
serialized, not walked.

**Middle Man** — a class or method that mostly just delegates onward.
→ Cut it and call the real target directly.
**Not this, twice.** A §architecture View that forwards input to its Controller and renders what comes back is doing its
whole job; the delegation is the layer boundary. And TheOne's Data Controllers exist precisely to stop direct
data access (§frameworks), so their delegation is the point.

**Refused Bequest** — a subclass that ignores or overrides most of what it inherits.
→ Drop the inheritance and use composition.
In Unity this shows up as a base MonoBehaviour whose `virtual` methods are all overridden to empty. Check
whether the base wanted to be an interface, or a component the subclass holds.
