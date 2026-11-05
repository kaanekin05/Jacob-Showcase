---
name: plain-decision-questions
description: Use when asking the user to choose between options.
category: general
---

# Explain each option's effect before asking for a choice

Before you ask a decision question, write each option as what happens if it is picked: to the game, the player, or the code. One plain sentence per option. If the effect is abstract, add one concrete example with a number or a level.

- Lead with your recommendation and one line of why.
- Name each option's cost, not only its benefit.
- Ask one decision at a time. Phrase it so that "yes" accepts the recommendation.
- Name the player-visible result first, then the code cost. "A returning player may replay one level once" lands before "the append rule is skipped".
- When the user asks for a plan first, show the complete plan before any tool work, even for a small build. The user may be new to the project and cannot judge a partial answer.
- When the user says they do not follow, restate the choice as numbered steps with the example, then ask again. Do not repeat the abstract wording.
- Define each project term in the question itself, such as rung, bake, seed, or hardness. A user who is lost cannot answer a question built on words they did not use. Use the user's own words for the thing they care about.
- When the user asks when a decision was made, check the record first and name where it came from: the user, the design doc, or an earlier session. Never claim the user decided something the record does not show.
- When the user delegates the choice ("I dont care, you just decide with the best look"), stop asking. Pick the option that meets every hard constraint the user has already stated, implement it, and report the measured result. A second question after a delegation is the failure.
- Before you offer options, list the user's stated constraints, such as "no overlaps" or "keep height for the banner". Drop any option that breaks one. Never offer an option the user already ruled out.
- A bare reply such as "2" answers the last numbered question. If the reply could mean more than one option, state the one option it means in a sentence, then proceed. Do not guess silently.
- Look a fact up before you ask for it. If a tool, the filesystem, or a Drive listing can answer it, read it yourself. For a question about a vendor SDK's default or behavior, read the SDK's own guide first, such as the `Documents/` folder in its package, and quote the line that answers it. Ask only what the user alone can answer, such as a folder ID they hold or their phone's OS version. Asking for a folder's naming format that a listing shows is a wasted question.
- Do not re-ask for something the user already told you to do. "Lets fix the 8 errors" is an instruction. Do the local, reversible fixes, then ask only about the outward step, such as a push, a new public repo, or a visibility change.
