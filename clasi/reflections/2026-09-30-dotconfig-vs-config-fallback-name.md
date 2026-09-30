---
date: 2026-09-30
sprint: none (out-of-process change)
category: emergent-gap
---

# Implemented `.config` when the stakeholder meant `.dotconfig`

## What Happened

The stakeholder asked: "Does dotconfig look for .dotconfig as a directory
for secrets?" In the next message they said: "Add .config as a second
option if the config directory is not found…". I noticed the mismatch
with the earlier question. I resolved it myself in favour of the literal
text, reasoning that the `dotconfig config` help already used
`DOTCONFIG_NAME=.config` as an example. I then implemented, tested,
committed and version-bumped `.config/` as the fallback. I flagged the
choice only in my closing summary. The stakeholder corrected me: "no not
.config, I want it to be .dotconfig".

## What Should Have Happened

The literal text conflicted with the immediately preceding question, and
the stakeholder's messages are often dictated (speech-to-text). I should
have treated that as a genuine ambiguity. One short confirmation ("`.dotconfig`,
as in your question, or literally `.config`?") would have cost a few
seconds. It would have avoided a wrong commit, a version bump and a
correction commit.

## Root Cause

Emergent gap. No rule covers reconciling a literal instruction with
conflicting context from the same conversation. The general guidance
("when you have enough information to act, act") pushed toward
proceeding. Here the "information" contradicted itself, and I picked the
side supported by a weaker signal (an example in help text) over the
stronger one (the stakeholder's own question one turn earlier).

## Proposed Fix

- When a stakeholder's instruction names something (a file, directory,
  flag or command) that differs from what they named moments earlier,
  confirm which one they mean before implementing. This applies
  especially when the difference looks like a dictation slip (`.config`
  vs `.dotconfig`).
- If I proceed anyway, prefer the reading consistent with the
  stakeholder's own earlier words over incidental evidence in the code.

No code or process TODO is needed. The fix is behavioural, and I've
saved it as a feedback memory.
