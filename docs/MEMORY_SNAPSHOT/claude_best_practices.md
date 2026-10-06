---
name: claude-best-practices-karpathy
description: "Best practices из andrej-karpathy-skills (CLAUDE.md) — lean, focused, verification-driven"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: a036e65c-5740-455e-9c14-1573bb7db59d
---

# Claude Best Practices (from andrej-karpathy-skills)

**Источник:** https://github.com/multica-ai/andrej-karpathy-skills/blob/main/CLAUDE.md  
**Дата адаптации:** 27.06.2026  
**Статус:** Заимствовано для улучшения workflow

---

## 4 Core Rules for Effective Coding

### 1. Deliberate Analysis Before Implementation
**Rule:** State your assumptions explicitly. If uncertain, ask.

- Surface confusion and tradeoffs rather than proceeding blindly
- Present multiple interpretations when ambiguity exists
- Pause if anything remains unclear
- Verify understanding with user BEFORE coding

**Why:** Prevents rebuilding after misunderstanding. Clarifying upfront saves rework.

**How to apply:**
- When request is ambiguous → list 2-3 interpretations + ask which
- When tradeoffs exist → present them explicitly (speed vs quality, simplicity vs robustness)
- Never assume context — ask if knowledge gap exists

---

### 2. Lean, Focused Solutions
**Rule:** Deliver only requested functionality—no speculative features

- Avoid unnecessary abstractions in single-use contexts
- Skip error handling for unrealistic scenarios
- Don't refactor surrounding code unless YOUR changes break it
- **Test:** Would a seasoned engineer call this bloated? Simplify if yes.

**Why:** Over-engineering creates maintenance debt. Minimal code is faster to review and debug.

**How to apply:**
- Before adding a helper function: "Is this used more than once?"
- Before adding error handling: "Can this condition realistically happen?"
- Before abstracting: "Would 3+ similar patterns justify this?"
- Feature: Check task scope. Is it in scope? If no → backlog, not this PR.

---

### 3. Minimal, Targeted Edits
**Rule:** Modify only what the request requires

- Preserve existing code style without "improvements"
- Clean up only dependencies YOUR changes broke
- Flag unrelated dead code instead of removing it silently
- Change one variable name = ONE edit, not "while I'm here" edits

**Why:** Tight diffs are easier to review. Silent cleanup masks intent changes.

**How to apply:**
- If task is "add feature X" → don't rename surrounding variables
- If task breaks import Y → fix import Y, not refactor file
- If you find dead code → mention in task wrap-up, don't delete
- Diff should show ONLY what you changed for THIS task

---

### 4. Verification-Driven Workflow
**Rule:** Convert requests into testable success criteria

- Create plan with steps and corresponding verification points
- Loop until goals are demonstrably met
- Weak criteria ("make it work") demand ongoing clarification with user
- Verification = run it, observe outcome, confirm it matches spec

**Why:** Prevents ambiguous "done" states. Both you and user know when it's done.

**How to apply:**
- Task: "Fix the bug" → Failure mode? Reproduce? Expected behavior? Fix? Test?
- Task: "Add feature X" → What does X do? How do you know it works? Test it.
- Each step should have a **specific** success condition (not "seems right")
- Loop with user: "Does this match your expectation?" (not assuming)

---

## Effectiveness Indicators

✅ **You're doing this well if:**
- Diffs are clean and focused (only changes related to task)
- Clarifying questions happen BEFORE implementation (not after)
- User confirms each major step (not surprised at the end)
- Code is simple enough that a colleague wouldn't ask "why this abstraction?"

❌ **Red flags:**
- Large diffs with unrelated cleanups
- Implementation started before requirements were clear
- "Make it work" and iterating blindly
- Over-engineered solutions for single-use cases
- Silent removal of code without noting it

---

## How This Aligns with Your Existing Practices

**Already doing:** ✅
- Grep before claim (verification-driven)
- Minimal changes per commit (targeted edits)
- Asking for clarification when uncertain (deliberate analysis)
- Not adding "just in case" features (lean solutions)

**To emphasize:**
- ✅ Keep the "tight diff" culture — this is gold
- ✅ Keep asking before assuming — this prevents rework
- ✅ Verify each step — this is your strength

**From Karpathy's approach to adopt:**
- Explicit success criteria BEFORE starting (not after)
- "Would a seasoned engineer call this bloated?" test (ruthless simplicity check)
- Flagging dead code instead of silently removing (transparency)
- Presenting multiple interpretations when ambiguous (preventing assumptions)

---

## Integration Points

**In your workflow:**
1. **Planning phase:** List assumptions + verification points
2. **Implementation:** Only touch code in scope
3. **Verification:** Run/test each step, confirm with user
4. **Commit:** Tight diff, only for this task

**In CLAUDE.md for project:**
- Add section: "4 Core Rules (Karpathy approach)"
- Link back to this file for detailed guidance

---

## References

- Source: https://github.com/multica-ai/andrej-karpathy-skills/blob/main/CLAUDE.md
- Your existing: `CLAUDE.md` (project), `memory/feedback_rules_table.md`, preflight rules
- Complementary: [[principle_reuse_not_duplication]], [[grep_before_claim]]
