---
name: fix-bug
description: Root-cause bug fixing. Use whenever Collins reports a bug, error, failing test, crash, wrong output, or says "fix", "broken", "not working". Find the cause before touching code; no guess-patching.
---

# Fix a bug

No fix until you know the root cause. A patch that hides the symptom is a failure.

1. **Read the error.** Full message and stack trace. Note file:line. Don't skim.
2. **Reproduce.** Find the exact command, request or input that triggers it. Can't reproduce? Ask Collins ONE question for the missing detail; don't guess.
3. **Narrow it.** `git log -p -5 -- <file>` and `git diff` for recent changes. Grep every caller of the failing function. Compare with a similar piece of code that works.
4. **One hypothesis.** Say it in one line: "X fails because Y." Test it with the smallest check (a print, an assert, one query). Wrong? Next hypothesis. Never change two things at once.
5. **Failing test first.** Write a test that reproduces the bug and fails for the right reason.
6. **One fix, at the root.** If the bug is in shared code, fix it there once, not in every caller. Smallest diff that makes the test pass.
7. **Verify.** Run the new test and the existing suite. Paste the pass/fail lines, not the whole log.

**3 fixes failed?** Stop. The design is probably wrong. Tell Collins what you tried, what you learned, and what you think needs to change.

Report, max 8 lines:
- **Cause:** one line, file:line
- **Fix:** what changed and why it's the root
- **Proof:** test command + result
- **Risk:** anything else that could hit the same cause
