---
name: game-design-docs
description: Use when writing or reviewing a game design document (GDD), system spec, or feature design. Enforces a structured, testable format so designs are precise, balanced from mathematical foundations, and free of vague language. Trigger keywords — GDD, design doc, system spec, feature design, game design, balance, tuning, acceptance criteria.
---

# Game Design Document Standards

On-demand format for game design specs. Engine-agnostic. The goal is a design a
programmer can implement and a QA tester can verify *without asking the designer
what something means*. Precision, testability, and interconnected-system thinking
over prose.

## Document-level practices
Before the per-system rigor below, get the macro framing right:
- **Open with design pillars and explicit non-goals.** Three to five pillars define
  what the game *is*; non-goals state what it deliberately is *not*. Every later
  decision is checked against them. Start broad (one-line pitch → pillars → non-goals)
  then get specific.
- **Treat the GDD as a living document, not a deliverable.** It evolves with every
  mechanic test and rewrite. A frozen GDD is a dead one — version it and keep it current.
- **Write for scanning.** Short sections, lists, clear headings. Most readers skim;
  bury nothing critical in prose.
- **Show, don't only tell.** Diagrams, state charts, flowcharts, and mockups
  communicate systems faster than paragraphs — include them for anything non-trivial.
- **Right-size to the team.** Document the depth the team needs and no more; an
  unmaintained 100-page doc is worse than a tight one that stays true.

## Required sections
Every system/feature design must contain these eight, in order:

1. **Overview** — what the system is and the problem it solves, in two or three sentences.
2. **Player Fantasy** — the experience the player should have. The only place
   subjective language belongs; everything below must be concrete.
3. **Detailed Rules** — the exact mechanics, states, and interactions. Unambiguous.
4. **Formulas** — every formula with **variable definitions, expected value ranges,
   and at least one worked example calculation**. No bare expressions.
5. **Edge Cases** — boundary conditions, failure states, conflicts with other systems.
6. **Dependencies** — which systems this relies on and which rely on it. Document
   dependencies **bidirectionally**: if System A references System B, B's doc must
   record the inbound link from A.
7. **Tuning Knobs** — the values designers will iterate on, with default + range.
   These map to data-driven config (§architecture — no hardcoded gameplay values).
8. **Acceptance Criteria** — testable pass/fail statements. Each must be checkable
   by a QA tester or an automated test, not a judgment call.

## Rigor rules
- **No vague language.** "Feels good", "snappy", "balanced" are banned outside
  Player Fantasy. Replace with measurable targets (timings, ranges, thresholds).
- **Balance traces to math.** Every balance value cites its formula or a written
  justification — never an unexplained constant.
- **Specs are testable, not subjective.** If a line can't become an acceptance
  criterion or a test, it's not a spec — it's a note.
- **Tuning knobs are data, not code.** Anything in section 7 must end up in a
  ScriptableObject / config file, consistent with the data-driven rule in §architecture.

## Anti-patterns
- DO NOT ship a formula without variable definitions, ranges, and a worked example.
- DO NOT record a dependency in one direction only.
- DO NOT use subjective adjectives as if they were specifications.
- DO NOT hardcode tuning values into the design as fixed constants — express them as knobs.
